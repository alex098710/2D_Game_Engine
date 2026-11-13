from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.admin.router import get_admin_repository
from app.auth.dependencies import current_user
from app.auth.user import User
from app.main import app
from app.projects.router import current_owner_id, get_repository
from tests.test_projects import FakeProjectRepository


class FakeAdminRepository:
    def __init__(self):
        self.balances = {}
        self.rows = []

    def balance(self, user_id):
        return self.balances.get(user_id, {"heroes": {}, "enemies": {}})

    def save_balance(self, user_id, heroes, enemies):
        self.balances[user_id] = {"heroes": heroes, "enemies": enemies}
        return self.balances[user_id]

    def creations(self, user_id):
        return [dict(row) for row in self.rows if row["owner_id"] == user_id]

    def count(self, user_id):
        return len(self.creations(user_id))

    def create(self, user_id, values):
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        row = {"id": len(self.rows) + 1, "owner_id": user_id, **values, "created_at": now, "updated_at": now}
        self.rows.append(row)
        return dict(row)

    def update(self, user_id, creation_id, values):
        for row in self.rows:
            if row["id"] == creation_id and row["owner_id"] == user_id:
                row.update(values)
                return dict(row)
        return None

    def delete(self, user_id, creation_id):
        before = len(self.rows)
        self.rows = [r for r in self.rows if not (r["id"] == creation_id and r["owner_id"] == user_id)]
        return len(self.rows) < before


def client_for(user_id=1, repo=None):
    repo = repo or FakeAdminRepository()
    app.dependency_overrides[get_admin_repository] = lambda: repo
    app.dependency_overrides[current_user] = lambda: User(user_id, f"user{user_id}", f"u{user_id}@example.com", b"s", b"h")
    return TestClient(app), repo


def teardown_function():
    app.dependency_overrides.clear()


ORC = {"category": "enemy", "base_kind": "brute", "name": "Ogro de hielo", "tint": "#7FD4FF",
       "health": 12, "damage": 3, "speed": 50}


def test_balance_starts_empty_and_is_saved_per_account():
    client, repo = client_for()
    assert client.get("/me/balance").json() == {"heroes": {}, "enemies": {}}
    body = {"heroes": {"knight": {"health": 9, "damage": 3}}, "enemies": {"brute": {"health": 20, "damage": 4}}}
    assert client.put("/me/balance", json=body).json() == body
    other, _ = client_for(2, repo)
    assert other.get("/me/balance").json() == {"heroes": {}, "enemies": {}}


def test_balance_rejects_unknown_names_and_numbers_out_of_range():
    client, _ = client_for()
    for body in [
        {"heroes": {"dragon": {"health": 5, "damage": 1}}},
        {"heroes": {"knight": {"health": 0, "damage": 1}}},
        {"heroes": {"knight": {"health": 5, "damage": 11}}},
        {"enemies": {"tree": {"health": 5, "damage": 1}}},
        {"enemies": {"brute": {"health": 100, "damage": 1}}},
    ]:
        assert client.put("/me/balance", json=body).status_code == 422


def test_the_new_soldier_heroes_can_be_balanced():
    client, _ = client_for()
    body = {"heroes": {"soldier": {"health": 8, "damage": 3}, "commando": {"health": 6, "damage": 2},
                       "warrior": {"health": 9, "damage": 4}}, "enemies": {}}
    assert client.put("/me/balance", json=body).status_code == 200


def test_create_list_update_and_delete_a_creation():
    client, _ = client_for()
    created = client.post("/me/creations", json=ORC)
    assert created.status_code == 201
    orc = created.json()
    assert (orc["name"], orc["tint"], orc["health"]) == ("Ogro de hielo", "#7fd4ff", 12)
    assert [c["id"] for c in client.get("/me/creations").json()] == [orc["id"]]
    changed = client.put(f"/me/creations/{orc['id']}", json={**ORC, "name": "Ogro de fuego", "tint": "#ff6b3d"})
    assert changed.json()["name"] == "Ogro de fuego"
    assert client.delete(f"/me/creations/{orc['id']}").status_code == 204
    assert client.get("/me/creations").json() == []


def test_creations_are_private_to_their_account():
    client, repo = client_for()
    orc = client.post("/me/creations", json=ORC).json()
    other, _ = client_for(2, repo)
    assert other.get("/me/creations").json() == []
    assert other.put(f"/me/creations/{orc['id']}", json=ORC).status_code == 404
    assert other.delete(f"/me/creations/{orc['id']}").status_code == 404


def test_a_creation_must_fit_its_category():
    client, _ = client_for()
    assert client.post("/me/creations", json={**ORC, "base_kind": "tree"}).status_code == 422
    assert client.post("/me/creations", json={**ORC, "health": 0}).status_code == 422
    assert client.post("/me/creations", json={**ORC, "name": "   "}).status_code == 422
    assert client.post("/me/creations", json={**ORC, "tint": "red"}).status_code == 422
    hero = {"category": "hero", "base_kind": "soldier", "name": "Sargento", "health": 7, "damage": 2, "speed": 180}
    assert client.post("/me/creations", json=hero).status_code == 201
    assert client.post("/me/creations", json={**hero, "speed": 50}).status_code == 422


def test_an_object_keeps_only_the_value_that_means_something():
    client, _ = client_for()
    potion = client.post("/me/creations", json={"category": "object", "base_kind": "potion", "name": "Elixir",
                                                "value": 5, "health": 9, "damage": 9}).json()
    assert (potion["value"], potion["health"], potion["damage"]) == (5, 0, 0)
    chest = client.post("/me/creations", json={"category": "object", "base_kind": "chest", "name": "Cofre real",
                                               "value": 5}).json()
    assert chest["value"] == 0


def test_there_is_a_limit_of_creations_per_account():
    client, repo = client_for()
    for i in range(60):
        repo.create(1, {**ORC, "name": f"Ogro {i}", "value": 0})
    assert client.post("/me/creations", json=ORC).status_code == 422


# --- creations placed in a scene ---------------------------------------------------------------

class ProjectsWithCreations(FakeProjectRepository):
    def __init__(self, creations):
        super().__init__()
        self._creations = creations  # {owner: {id: base kind}}

    def creation_kinds(self, owner_id, ids):
        mine = self._creations.get(owner_id, {})
        return {i: mine[i] for i in ids if i in mine}


def projects_client(owner_id=1):
    repo = ProjectsWithCreations({1: {7: "brute"}, 2: {9: "brute"}})
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[current_owner_id] = lambda: owner_id
    client = TestClient(app)
    project_id = client.post("/projects", json={"name": "p"}).json()["id"]
    return client, project_id


def test_a_scene_can_place_the_owners_creation():
    client, project_id = projects_client()
    scene = [{"id": "o", "kind": "brute", "x": 100, "y": 100, "variant": 7}, {"id": "c", "kind": "coin", "x": 5, "y": 5}]
    saved = client.put(f"/projects/{project_id}/scene", json={"scene": scene}).json()["scene"]
    assert saved[0]["variant"] == 7
    assert "variant" not in saved[1]  # plain objects are stored as before


def test_a_scene_cannot_use_someone_elses_creation_or_the_wrong_kind():
    client, project_id = projects_client()
    for obj in [{"id": "o", "kind": "brute", "x": 1, "y": 1, "variant": 9},
                {"id": "o", "kind": "ghost", "x": 1, "y": 1, "variant": 7}]:
        assert client.put(f"/projects/{project_id}/scene", json={"scene": [obj]}).status_code == 422
