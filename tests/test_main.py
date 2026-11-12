from fastapi.testclient import TestClient

from app.database import database_connection
from app.main import app


def test_health_answers_ok():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_every_response_has_security_headers():
    response = TestClient(app).get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_docs_keep_working_without_the_strict_csp():
    response = TestClient(app).get("/docs")
    assert response.status_code == 200
    assert "content-security-policy" not in response.headers


def test_health_db_checks_the_database_but_tells_nothing_about_it():
    class FakeConnection:
        def execute(self, sql):
            class Result:
                def fetchone(self):
                    return {"?column?": 1}
            return Result()

    app.dependency_overrides[database_connection] = lambda: FakeConnection()
    try:
        assert TestClient(app).get("/health/db").json() == {"ok": True}
    finally:
        app.dependency_overrides.clear()


def test_cors_allows_the_frontend_origin():
    response = TestClient(app).options(
        "/auth/login",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_uptime_monitors_can_check_with_head():
    # UptimeRobot sends HEAD; a 405 marked the API as down although it was up.
    class FakeConnection:
        def execute(self, sql):
            class Result:
                def fetchone(self):
                    return {"?column?": 1}
            return Result()

    app.dependency_overrides[database_connection] = lambda: FakeConnection()
    try:
        client = TestClient(app)
        for path in ("/health", "/health/db"):
            response = client.head(path)
            assert response.status_code == 200
            assert response.content == b""
    finally:
        app.dependency_overrides.clear()
