"""Account requests sealed as one encrypted block (app/auth/sealed.py)."""
import pytest
from fastapi.testclient import TestClient

from app.auth import sealed
from app.auth.sealed import SealedError, new_challenge, open_answer_for_tests, open_sealed, seal_for_tests
from app.main import app


def test_a_sealed_block_opens_once_and_only_once():
    challenge = new_challenge()
    block, key = seal_for_tests({"email": "a@b.co", "password": "secreto-123"}, challenge)
    data, opened_key = open_sealed(block)
    assert data == {"email": "a@b.co", "password": "secreto-123"}
    assert opened_key == key
    with pytest.raises(SealedError):
        open_sealed(block)  # a copied block cannot be replayed


def test_the_block_hides_the_password():
    block, _ = seal_for_tests({"password": "secreto-123"}, new_challenge())
    assert "secreto" not in block and "password" not in block


def test_unknown_expired_or_tampered_blocks_are_refused():
    challenge = new_challenge()
    block, _ = seal_for_tests({"x": 1}, challenge)
    parts = block.split(".")
    tampered = ".".join(parts[:4] + [parts[4][:-2] + ("AA" if parts[4][-2:] != "AA" else "BB")])
    with pytest.raises(SealedError):
        open_sealed(tampered)
    with pytest.raises(SealedError):
        open_sealed(block)  # the failed try burned the challenge too
    with pytest.raises(SealedError):
        open_sealed("v1.nope.a.b.c")
    with pytest.raises(SealedError):
        open_sealed("not a block")


def test_an_expired_challenge_is_refused(monkeypatch):
    now = [1000.0]
    cache = sealed.LRUCache(capacity=10, ttl_seconds=sealed.CHALLENGE_TTL, clock=lambda: now[0])
    monkeypatch.setattr(sealed, "_challenges", cache)
    challenge = new_challenge()
    block, _ = seal_for_tests({"x": 1}, challenge)
    now[0] += sealed.CHALLENGE_TTL + 1
    with pytest.raises(SealedError):
        open_sealed(block)


def test_the_challenge_endpoint_is_never_cached():
    reply = TestClient(app).get("/auth/challenge")
    assert reply.status_code == 200
    assert reply.headers["cache-control"] == "no-store"
    assert set(reply.json()) == {"id", "key", "alg", "expires_in"}


def test_a_sealed_login_gets_a_sealed_answer(monkeypatch):
    from tests.test_auth_routes import make_client  # the in-memory auth service of the API tests

    client = make_client()
    client.post("/auth/register", json={"username": "sellado", "email": "s@e.co", "password": "Contrasena-Larga-1"})
    challenge = client.get("/auth/challenge").json()
    block, key = seal_for_tests({"email": "s@e.co", "password": "Contrasena-Larga-1"}, challenge)

    reply = client.post("/auth/login", json={"sealed": block})

    assert reply.status_code == 200
    assert set(reply.json()) == {"sealed"}  # no token in clear
    tokens = open_answer_for_tests(reply.json(), key)
    assert "access_token" in tokens and "refresh_token" in tokens
    # The same block a second time: refused, it was single use.
    assert client.post("/auth/login", json={"sealed": block}).status_code == 400


def test_a_sealed_body_with_bad_fields_never_echoes_the_password():
    from tests.test_auth_routes import make_client

    client = make_client()
    block, _ = seal_for_tests({"email": "x@y.co", "password": ""}, client.get("/auth/challenge").json())
    reply = client.post("/auth/login", json={"sealed": block})
    assert reply.status_code == 422
    assert "input" not in reply.text


def teardown_function():
    app.dependency_overrides.clear()
