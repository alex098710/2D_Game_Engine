"""Tests for the security layer: configuration checks, rate limits, body size,
request ids, error handling, password policy and the JWT audience."""
import jwt
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.auth.dependencies import get_auth_service, get_commit
from app.auth.errors import InvalidCredentialsError
from app.auth.jwt_codec import JwtCodec
from app.auth.password_policy import WeakPasswordError, check_password
from app.body_limit import MAX_BODY_BYTES
from app.config import InsecureConfigurationError, check_configuration, configuration_problems
from app.main import app
from app.rate_limit import SlidingWindowLimiter, client_ip
from tests.fakes import TEST_JWT_SECRET, AuthFixture

GOOD_SECRET = "Zq8-vR3p_Lk2mN7xT5wY1bC9dF4gH6jK0aS"
GOOD_ENV = {
    "JWT_SECRET": GOOD_SECRET,
    "DATABASE_URL": "postgresql://db",
    "FRONTEND_ORIGINS": "https://game.example.com",
    "AI_SERVICE_URL": "https://ai.example.com",
    "AI_SERVICE_KEY": GOOD_SECRET[::-1],
}


# --- configuration -----------------------------------------------------------

def test_a_good_configuration_has_no_problems():
    assert configuration_problems({**GOOD_ENV, "ENVIRONMENT": "production"}) == []


def test_weak_and_example_secrets_are_reported():
    problems = configuration_problems({**GOOD_ENV, "JWT_SECRET": "change-me-to-a-long-random-string-of-48-chars"})
    assert any("example value" in p for p in problems)
    assert any("at least 32" in p for p in configuration_problems({**GOOD_ENV, "JWT_SECRET": "short"}))
    assert any("not random" in p for p in configuration_problems({**GOOD_ENV, "JWT_SECRET": "ab" * 20}))


def test_production_requires_https_origins_and_no_wildcard():
    env = {**GOOD_ENV, "ENVIRONMENT": "production", "FRONTEND_ORIGINS": "http://game.example.com,*"}
    problems = configuration_problems(env)
    assert any("https" in p for p in problems)
    assert any("'*'" in p for p in problems)


def test_relaxed_rate_limits_are_refused_in_production():
    env = {**GOOD_ENV, "ENVIRONMENT": "production", "RATE_LIMIT_MULTIPLIER": "20"}
    assert any("RATE_LIMIT_MULTIPLIER" in p for p in configuration_problems(env))
    assert configuration_problems({**GOOD_ENV, "RATE_LIMIT_MULTIPLIER": "20"}) == []


def test_production_refuses_to_start_but_development_only_warns():
    weak = {**GOOD_ENV, "JWT_SECRET": ""}
    with pytest.raises(InsecureConfigurationError):
        check_configuration({**weak, "ENVIRONMENT": "production"})
    assert check_configuration(weak) == ["JWT_SECRET is not set"]


# --- rate limiting -----------------------------------------------------------

def test_sliding_window_allows_the_limit_then_blocks_until_the_window_moves():
    now = [0.0]
    limiter = SlidingWindowLimiter(clock=lambda: now[0])
    assert [limiter.hit("k", 3, 60) for _ in range(3)] == [0.0, 0.0, 0.0]
    assert limiter.hit("k", 3, 60) == 60.0
    now[0] = 61
    assert limiter.hit("k", 3, 60) == 0.0
    assert limiter.hit("other", 3, 60) == 0.0


def test_the_limiter_forgets_clients_that_went_quiet():
    now = [0.0]
    limiter = SlidingWindowLimiter(clock=lambda: now[0])
    for n in range(500):
        limiter.hit(f"old-{n}", 10, 60)
    assert limiter.size() == 500
    now[0] = 120  # every old client is past its window
    for _ in range(SlidingWindowLimiter.SWEEP_EVERY):
        limiter.hit("active", 10_000, 60)
    assert limiter.size() == 1


def test_login_failures_are_counted_by_the_real_client_address(monkeypatch):
    from app.auth.router import _client_ip

    class FakeRequest:
        scope = {"client": ("10.0.0.1", 1), "headers": [(b"x-forwarded-for", b"6.6.6.6")]}

    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert _client_ip(FakeRequest()) == "6.6.6.6"
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    assert _client_ip(FakeRequest()) == "10.0.0.1"


def test_forwarded_for_is_trusted_only_behind_known_proxies():
    scope = {"client": ("10.0.0.1", 1), "headers": [(b"x-forwarded-for", b"6.6.6.6, 1.2.3.4")]}
    assert client_ip(scope) == "10.0.0.1"
    assert client_ip(scope, trusted_proxy_hops=1) == "1.2.3.4"
    assert client_ip({"headers": []}) == "unknown"


def test_on_render_the_edge_header_names_the_visitor():
    from app.rate_limit import proxy_settings

    # What Render passes on: whatever the client wrote first, then the visitor, Cloudflare and Render.
    scope = {"client": ("10.0.0.9", 1), "headers": [
        (b"x-forwarded-for", b"6.6.6.6, 81.107.0.110, 172.71.1.1, 10.0.0.9"),
        (b"cf-connecting-ip", b"81.107.0.110"),
    ]}
    hops, edge = proxy_settings({"RENDER": "true"})
    assert (hops, edge) == (3, True)
    assert client_ip(scope, hops, edge) == "81.107.0.110"
    # Without the edge header, X-Forwarded-For read from the end gives the same visitor, never the fake 6.6.6.6.
    assert client_ip(scope, hops, False) == "81.107.0.110"


def test_edge_headers_are_ignored_off_render_and_garbage_is_never_a_key():
    from app.rate_limit import proxy_settings

    scope = {"client": ("10.0.0.1", 1), "headers": [(b"cf-connecting-ip", b"1.2.3.4"), (b"x-forwarded-for", b"not-an-ip")]}
    hops, edge = proxy_settings({})
    assert (hops, edge) == (0, False)
    assert client_ip(scope, hops, edge) == "10.0.0.1"
    assert client_ip(scope, 1, False) == "10.0.0.1"  # a bad X-Forwarded-For falls back to the socket
    assert client_ip({"headers": [(b"cf-connecting-ip", b"<script>")], "client": ("10.0.0.1", 1)}, 0, True) == "10.0.0.1"
    assert proxy_settings({"RENDER": "true", "TRUSTED_PROXY_HOPS": "1", "TRUST_EDGE_IP_HEADER": "0"}) == (1, False)


def test_login_is_limited_to_ten_attempts_a_minute():
    service = AuthFixture().service
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_commit] = lambda: (lambda: None)
    try:
        client = TestClient(app)
        body = {"email": "x@example.com", "password": "whatever"}
        codes = [client.post("/auth/login", json=body).status_code for _ in range(11)]
    finally:
        app.dependency_overrides.clear()
    assert codes[:10] == [401] * 5 + [429] * 5  # the account lockout kicks in after 5
    assert codes[10] == 429
    response = TestClient(app).post("/auth/login", json=body)
    assert response.json() == {"detail": "Too many requests, slow down"}
    assert int(response.headers["retry-after"]) > 0


def test_cors_preflight_is_never_rate_limited():
    client = TestClient(app)
    headers = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    assert all(client.options("/auth/login", headers=headers).status_code == 200 for _ in range(20))


# --- body size, request id and errors ----------------------------------------

def test_huge_bodies_are_rejected_with_413():
    big = "x" * (MAX_BODY_BYTES + 1)
    response = TestClient(app).post("/auth/login", content=big, headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_every_response_has_a_request_id_and_a_safe_one_is_echoed():
    client = TestClient(app)
    assert len(client.get("/health").headers["x-request-id"]) == 32
    assert client.get("/health", headers={"X-Request-ID": "abc-12345"}).headers["x-request-id"] == "abc-12345"
    assert client.get("/health", headers={"X-Request-ID": "<script>"}).headers["x-request-id"] != "<script>"


def test_unexpected_errors_do_not_leak_details():
    boom = APIRouter()

    @boom.get("/__boom")
    def explode():
        raise RuntimeError("database password is hunter2")

    app.include_router(boom)
    try:
        response = TestClient(app, raise_server_exceptions=False).get("/__boom")
    finally:
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/__boom"]
    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_hsts_is_sent_behind_an_https_proxy():
    response = TestClient(app).get("/health", headers={"X-Forwarded-Proto": "https"})
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")
    assert "strict-transport-security" not in TestClient(app).get("/health").headers
    assert response.headers["permissions-policy"].startswith("camera=()")


# --- password policy ---------------------------------------------------------

@pytest.mark.parametrize("password, reason", [
    ("short", "at least 8"),
    ("password123", "too common"),
    ("aaaabbbb", "too few"),
    ("1234567899", "only numbers"),
    ("jesus-rocks-2026", "email or username"),
])
def test_weak_passwords_are_refused_with_a_reason(password, reason):
    with pytest.raises(WeakPasswordError, match=reason):
        check_password(password, "jesus@example.com", "jesus")


def test_a_good_password_passes():
    check_password("correct horse battery", "jesus@example.com", "jesus")


def test_register_returns_422_with_the_reason_for_a_weak_password():
    app.dependency_overrides[get_auth_service] = lambda: AuthFixture().service
    try:
        response = TestClient(app).post(
            "/auth/register", json={"username": "ana", "email": "ana@example.com", "password": "password123"}
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    assert response.json()["detail"] == "Password is too common"


# --- password change -----------------------------------------------------------

def test_change_password_revokes_every_refresh_token():
    fixture = AuthFixture()
    user = fixture.service.register("jesus", "jesus@example.com", "correct horse")
    pair = fixture.service.log_in("jesus@example.com", "correct horse")
    fixture.service.change_password(user, "correct horse", "a new long phrase")
    with pytest.raises(InvalidCredentialsError):
        fixture.service.log_in("jesus@example.com", "correct horse")
    assert fixture.service.log_in("jesus@example.com", "a new long phrase")
    assert fixture.refresh_tokens.find_by_hash(fixture.service._tokens.hash(pair.refresh_token)).revoked_at
    assert (user.id, "user.password_changed") in fixture.audit.entries


def test_change_password_checks_the_current_one_and_the_policy():
    fixture = AuthFixture()
    user = fixture.service.register("jesus", "jesus@example.com", "correct horse")
    with pytest.raises(InvalidCredentialsError):
        fixture.service.change_password(user, "wrong", "a new long phrase")
    with pytest.raises(WeakPasswordError):
        fixture.service.change_password(user, "correct horse", "password123")
    with pytest.raises(WeakPasswordError, match="different"):
        fixture.service.change_password(user, "correct horse", "correct horse")


def test_change_password_route():
    fixture = AuthFixture()
    app.dependency_overrides[get_auth_service] = lambda: fixture.service
    app.dependency_overrides[get_commit] = lambda: (lambda: None)
    try:
        client = TestClient(app)
        client.post("/auth/register", json={"username": "ana", "email": "ana@example.com", "password": "correct horse"})
        token = client.post("/auth/login", json={"email": "ana@example.com", "password": "correct horse"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        wrong = client.post("/auth/password", json={"current_password": "nope", "new_password": "a new long phrase"}, headers=headers)
        ok = client.post("/auth/password", json={"current_password": "correct horse", "new_password": "a new long phrase"}, headers=headers)
        unauthenticated = client.post("/auth/password", json={"current_password": "x", "new_password": "a new long phrase"})
    finally:
        app.dependency_overrides.clear()
    assert (wrong.status_code, ok.status_code, unauthenticated.status_code) == (400, 204, 401)


# --- JWT audience ----------------------------------------------------------------

def test_access_tokens_carry_and_require_the_api_audience():
    token, _ = JwtCodec(TEST_JWT_SECRET).issue_access(1)
    claims = jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"], audience="2d-engine-api")
    assert claims["nbf"] == claims["iat"]
    other = jwt.encode({**claims, "aud": "ai-service"}, TEST_JWT_SECRET, algorithm="HS256")
    with pytest.raises(Exception):
        JwtCodec(TEST_JWT_SECRET).decode_access(other)


def test_errors_and_limits_keep_cors_headers_so_the_browser_can_read_them():
    origin = {"Origin": "http://localhost:5173"}
    boom = APIRouter()

    @boom.get("/__boom_cors")
    def explode():
        raise RuntimeError("secret detail")

    app.include_router(boom)
    try:
        failed = TestClient(app, raise_server_exceptions=False).get("/__boom_cors", headers=origin)
    finally:
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/__boom_cors"]
    too_big = TestClient(app).post("/auth/login", content="x" * (MAX_BODY_BYTES + 1),
                                   headers={**origin, "Content-Type": "application/json"})
    for response in (failed, too_big):
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert failed.status_code == 500 and "secret" not in failed.text


def test_validation_errors_never_echo_what_was_sent():
    from app.main import app as api
    from tests.test_auth_routes import make_client

    secret = "x" * 200 + "-mi-contrasena"
    try:
        reply = make_client().post("/auth/login", json={"email": "a@b.co", "password": secret})
    finally:
        api.dependency_overrides.clear()
    assert reply.status_code == 422
    assert "mi-contrasena" not in reply.text and "input" not in reply.text
    assert reply.json()["detail"][0]["loc"] == ["body", "password"]
