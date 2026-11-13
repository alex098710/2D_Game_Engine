from dataclasses import replace
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.projects.project import Project
from app.projects.router import current_owner_id, get_repository


class FakeProjectRepository:
    """In-memory stand-in with the same interface, so the API is tested without a database."""

    def __init__(self):
        self._projects = {}
        self._next_id = 1
        self.versions = {}
        self.templates = {"village": {"name": "Aldea", "scene": [{"id": "h", "kind": "house", "x": 64, "y": 64}]}}

    def commit(self):
        self.commits = getattr(self, "commits", 0) + 1

    def create(self, owner_id, name, scene):
        project = Project(self._next_id, owner_id, name, scene, datetime.now(timezone.utc))
        self._projects[project.id] = project
        self._next_id += 1
        return project

    def list_by_owner(self, owner_id):
        return [p for p in self._projects.values() if p.owner_id == owner_id]

    def find_by_id(self, project_id, owner_id):
        project = self._projects.get(project_id)
        return project if project and project.owner_id == owner_id else None

    def update_scene(self, project_id, owner_id, scene):
        project = self.find_by_id(project_id, owner_id)
        if project is None:
            return None
        updated = replace(project, scene=scene, updated_at=datetime.now(timezone.utc))
        self._projects[project_id] = updated
        return updated

    def rename(self, project_id, owner_id, name):
        project = self.find_by_id(project_id, owner_id)
        if project is None:
            return None
        self._projects[project_id] = replace(project, name=name)
        return self._projects[project_id]

    def delete(self, project_id, owner_id):
        if self.find_by_id(project_id, owner_id) is None:
            return False
        del self._projects[project_id]
        return True

    def save_version(self, project_id, owner_id, scene, note=""):
        versions = self.versions.setdefault(project_id, [])
        versions.append({"version_number": len(versions) + 1, "note": note, "scene": scene,
                         "created_at": datetime.now(timezone.utc), "object_count": len(scene)})
        return len(versions)

    def list_versions(self, project_id):
        rows = self.versions.get(project_id, [])
        return [{k: v for k, v in row.items() if k != "scene"} for row in reversed(rows)]

    def find_version(self, project_id, version_number):
        for row in self.versions.get(project_id, []):
            if row["version_number"] == version_number:
                return row["scene"]
        return None

    def template_scene(self, code):
        return self.templates.get(code, {}).get("scene")

    def list_templates(self):
        return [{"code": c, "name": t["name"], "description": "", "object_count": len(t["scene"]), "scene": t["scene"]}
                for c, t in self.templates.items()]


def make_client(owner_id=1, repo=None):
    repo = repo or FakeProjectRepository()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[current_owner_id] = lambda: owner_id
    return TestClient(app), repo


def teardown_function():
    app.dependency_overrides.clear()


def test_create_project_returns_201_with_empty_scene():
    client, _ = make_client()
    response = client.post("/projects", json={"name": "level 1"})
    assert response.status_code == 201
    assert response.json()["name"] == "level 1"
    assert response.json()["scene"] == []


def test_save_and_load_scene_round_trip():
    client, _ = make_client()
    project_id = client.post("/projects", json={"name": "p"}).json()["id"]
    scene = [{"id": "a", "kind": "box", "x": 10.5, "y": 20.0}]

    saved = client.put(f"/projects/{project_id}/scene", json={"scene": scene})
    assert saved.status_code == 200

    loaded = client.get(f"/projects/{project_id}")
    assert loaded.json()["scene"] == scene


def test_list_returns_only_own_projects():
    client, repo = make_client(owner_id=1)
    repo.create(2, "someone else's", [])
    client.post("/projects", json={"name": "mine"})
    names = [p["name"] for p in client.get("/projects").json()]
    assert names == ["mine"]


def test_other_owner_cannot_read_or_write_a_project():
    client_a, repo = make_client(owner_id=1)
    project_id = client_a.post("/projects", json={"name": "private"}).json()["id"]

    client_b, _ = make_client(owner_id=2, repo=repo)
    assert client_b.get(f"/projects/{project_id}").status_code == 404
    assert client_b.put(f"/projects/{project_id}/scene", json={"scene": []}).status_code == 404


def test_invalid_scene_object_is_rejected():
    client, _ = make_client()
    project_id = client.post("/projects", json={"name": "p"}).json()["id"]
    bad = [{"id": "a", "kind": "box", "x": "not a number", "y": 0}]
    assert client.put(f"/projects/{project_id}/scene", json={"scene": bad}).status_code == 422


def test_missing_project_returns_404():
    client, _ = make_client()
    assert client.get("/projects/999").status_code == 404


def new_project(client, name="p"):
    return client.post("/projects", json={"name": name}).json()["id"]


def test_blank_or_too_long_names_are_rejected():
    client, _ = make_client()
    assert client.post("/projects", json={"name": "   "}).status_code == 422
    assert client.post("/projects", json={"name": "x" * 31}).status_code == 422
    assert client.post("/projects", json={"name": "x" * 30}).status_code == 201


def test_a_copy_keeps_its_name_within_the_limit():
    client, _ = make_client()
    project_id = new_project(client, "y" * 30)
    copy = client.post(f"/projects/{project_id}/duplicate").json()
    assert copy["name"].endswith(" (copia)")
    assert len(copy["name"]) <= 30


def test_project_names_are_trimmed():
    client, _ = make_client()
    assert client.post("/projects", json={"name": "  level 2  "}).json()["name"] == "level 2"


def test_create_from_a_template_copies_its_scene():
    client, _ = make_client()
    response = client.post("/projects", json={"name": "town", "template": "village"})
    assert response.status_code == 201
    assert [obj["kind"] for obj in response.json()["scene"]] == ["house"]


def test_unknown_template_is_rejected():
    client, _ = make_client()
    assert client.post("/projects", json={"name": "x", "template": "nope"}).status_code == 422


def test_list_templates():
    client, _ = make_client()
    assert [t["code"] for t in client.get("/projects/templates").json()] == ["village"]


def test_templates_carry_their_scene_for_the_map_preview():
    client, _ = make_client()
    village = client.get("/projects/templates").json()[0]
    assert village["object_count"] == len(village["scene"]) == 1
    assert village["scene"][0]["kind"] == "house"


def test_unknown_kinds_and_out_of_world_positions_are_rejected():
    client, _ = make_client()
    project_id = new_project(client)
    bad_kind = [{"id": "a", "kind": "dragon", "x": 1, "y": 1}]
    outside = [{"id": "a", "kind": "box", "x": 5000, "y": 1}]
    negative = [{"id": "a", "kind": "box", "x": 1, "y": -1}]
    for scene in (bad_kind, outside, negative):
        assert client.put(f"/projects/{project_id}/scene", json={"scene": scene}).status_code == 422


def test_every_new_kind_is_accepted():
    client, _ = make_client()
    project_id = new_project(client)
    from app.projects.world import OBJECT_KINDS

    kinds = list(OBJECT_KINDS)
    scene = [{"id": k, "kind": k, "x": 32, "y": 32} for k in kinds]
    assert client.put(f"/projects/{project_id}/scene", json={"scene": scene}).status_code == 200


def test_duplicate_ids_and_two_players_are_rejected():
    client, _ = make_client()
    project_id = new_project(client)
    dup = [{"id": "a", "kind": "box", "x": 1, "y": 1}, {"id": "a", "kind": "coin", "x": 2, "y": 2}]
    two_players = [{"id": "p1", "kind": "player", "x": 1, "y": 1}, {"id": "p2", "kind": "player", "x": 2, "y": 2}]
    assert client.put(f"/projects/{project_id}/scene", json={"scene": dup}).status_code == 422
    assert client.put(f"/projects/{project_id}/scene", json={"scene": two_players}).status_code == 422


def test_rename_project():
    client, _ = make_client()
    project_id = new_project(client)
    response = client.patch(f"/projects/{project_id}", json={"name": "renamed"})
    assert response.status_code == 200
    assert client.get(f"/projects/{project_id}").json()["name"] == "renamed"


def test_delete_project():
    client, _ = make_client()
    project_id = new_project(client)
    assert client.delete(f"/projects/{project_id}").status_code == 204
    assert client.get(f"/projects/{project_id}").status_code == 404
    assert client.delete(f"/projects/{project_id}").status_code == 404


def test_duplicate_project_copies_the_scene_with_a_new_id():
    client, _ = make_client()
    project_id = new_project(client, "level")
    scene = [{"id": "a", "kind": "wall", "x": 10, "y": 10}]
    client.put(f"/projects/{project_id}/scene", json={"scene": scene})
    copy = client.post(f"/projects/{project_id}/duplicate")
    assert copy.status_code == 201
    assert copy.json()["id"] != project_id
    assert copy.json()["name"] == "level (copia)"
    assert copy.json()["scene"] == [{"id": "a", "kind": "wall", "x": 10.0, "y": 10.0}]


def test_other_owner_cannot_rename_delete_or_duplicate():
    client_a, repo = make_client(owner_id=1)
    project_id = new_project(client_a)
    client_b, _ = make_client(owner_id=2, repo=repo)
    assert client_b.patch(f"/projects/{project_id}", json={"name": "x"}).status_code == 404
    assert client_b.delete(f"/projects/{project_id}").status_code == 404
    assert client_b.post(f"/projects/{project_id}/duplicate").status_code == 404
    assert client_b.get(f"/projects/{project_id}/versions").status_code == 404


def test_every_save_creates_a_version_and_a_version_can_be_restored():
    client, _ = make_client()
    project_id = new_project(client)
    first = [{"id": "a", "kind": "box", "x": 1, "y": 1}]
    client.put(f"/projects/{project_id}/scene", json={"scene": first, "note": "uno"})
    client.put(f"/projects/{project_id}/scene", json={"scene": []})
    versions = client.get(f"/projects/{project_id}/versions").json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert versions[1]["note"] == "uno"

    restored = client.post(f"/projects/{project_id}/versions/1/restore")
    assert restored.status_code == 200
    assert restored.json()["scene"] == [{"id": "a", "kind": "box", "x": 1.0, "y": 1.0}]
    assert client.post(f"/projects/{project_id}/versions/99/restore").status_code == 404


def test_templates_are_read_once_and_shared_with_project_creation():
    client, repo = make_client()
    calls = {"n": 0}
    original = repo.list_templates

    def counting():
        calls["n"] += 1
        return original()

    repo.list_templates = counting
    client.get("/projects/templates")
    client.get("/projects/templates")
    created = client.post("/projects", json={"name": "town", "template": "village"}).json()
    assert calls["n"] == 1
    # The project gets its own copy: editing it never changes the cached template.
    client.put(f"/projects/{created['id']}/scene", json={"scene": []})
    assert client.get("/projects/templates").json()[0]["object_count"] == 1


def test_templates_are_private_and_revalidated():
    client, _ = make_client()
    first = client.get("/projects/templates")
    assert first.headers["cache-control"].startswith("private")
    assert "Authorization" in first.headers["vary"]
    again = client.get("/projects/templates", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
