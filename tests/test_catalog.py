from fastapi.testclient import TestClient

from app.catalog.router import get_catalog
from app.main import app


class FakeCatalog:
    def character_lines(self):
        return [{"kind": "knight", "line": "Hola"}, {"kind": "knight", "line": "Adiós"}, {"kind": "wizard", "line": "Magia"}]


def test_character_lines_are_grouped_by_kind():
    app.dependency_overrides[get_catalog] = FakeCatalog
    try:
        body = TestClient(app).get("/catalog/characters").json()
    finally:
        app.dependency_overrides.clear()
    assert body == {"knight": ["Hola", "Adiós"], "wizard": ["Magia"]}


class CountingCatalog:
    calls = 0

    def enemies(self):
        CountingCatalog.calls += 1
        return [{"code": "bat", "name": "Murciélago", "health": 2}]


def test_catalog_is_served_from_memory_after_the_first_request():
    CountingCatalog.calls = 0
    app.dependency_overrides[get_catalog] = CountingCatalog
    try:
        client = TestClient(app)
        first = client.get("/catalog/enemies")
        second = client.get("/catalog/enemies")
    finally:
        app.dependency_overrides.clear()
    assert first.json() == second.json() == [{"code": "bat", "name": "Murciélago", "health": 2}]
    assert CountingCatalog.calls == 1


def test_catalog_answers_304_when_the_browser_already_has_it():
    app.dependency_overrides[get_catalog] = CountingCatalog
    try:
        client = TestClient(app)
        first = client.get("/catalog/enemies")
        tag = first.headers["etag"]
        again = client.get("/catalog/enemies", headers={"If-None-Match": tag})
        changed = client.get("/catalog/enemies", headers={"If-None-Match": '"otro"'})
    finally:
        app.dependency_overrides.clear()
    assert first.headers["cache-control"].startswith("public, max-age=")
    assert again.status_code == 304 and again.content == b""
    assert changed.status_code == 200


def test_private_routes_still_say_no_store():
    response = TestClient(app).get("/health")
    assert response.headers["cache-control"] == "no-store"


def test_a_weak_etag_from_a_proxy_still_gets_304():
    # Cloudflare turns the strong tag into W/"..." when it compresses the answer.
    from app.cache import etag_matches

    assert etag_matches('W/"abc"', '"abc"')
    assert etag_matches('"zzz", W/"abc"', '"abc"')
    assert etag_matches("*", '"abc"')
    assert not etag_matches('W/"abd"', '"abc"')
    assert not etag_matches("", '"abc"')
