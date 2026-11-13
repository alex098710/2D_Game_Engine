"""SQL integration tests for projects, runs, AI models, settings and the catalog.

They need TEST_DATABASE_URL pointing at a throw-away PostgreSQL that has run
`python -m app.migrate`. Every test is rolled back at the end.
"""
import os

import psycopg
import pytest
from psycopg.rows import dict_row

from app.ai_learning.repository import AiModelRepository, difficulty_of
from app.auth.user_repository import UserRepository
from app.catalog.router import CatalogRepository
from app.play.repository import PlayRepository
from app.play.schemas import RunResult
from app.projects.repository import ProjectRepository
from app.settings.repository import DEFAULTS, SettingsRepository

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="TEST_DATABASE_URL is not set")

RUN = RunResult(outcome="won", score=50, coins_collected=2, coins_total=3, enemies_defeated=1,
                damage_taken=0, deaths=0, duration_ms=1000,
                events=[{"kind": "coin", "x": 1, "y": 2, "at_ms": 10}])


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, prepare_threshold=None) as conn:
        yield conn
        conn.rollback()


@pytest.fixture
def user(connection):
    return UserRepository(connection).create("game-test", "game-test@example.com", b"\x01" * 16, b"\x02" * 64)


@pytest.fixture
def project(connection, user):
    return ProjectRepository(connection).create(user.id, "level", [{"id": "a", "kind": "box", "x": 1, "y": 1}])


def test_rename_and_delete_project(connection, user, project):
    repo = ProjectRepository(connection)
    assert repo.rename(project.id, user.id, "new name").name == "new name"
    assert repo.rename(project.id, user.id + 999, "x") is None
    assert repo.delete(project.id, user.id + 999) is False
    assert repo.delete(project.id, user.id) is True
    assert repo.find_by_id(project.id, user.id) is None


def test_versions_are_numbered_per_project(connection, user, project):
    repo = ProjectRepository(connection)
    assert repo.save_version(project.id, user.id, [], "first") == 1
    assert repo.save_version(project.id, user.id, project.scene) == 2
    versions = repo.list_versions(project.id)
    assert [v["version_number"] for v in versions] == [2, 1]
    assert versions[0]["object_count"] == 1
    assert repo.find_version(project.id, 1) == []
    assert repo.find_version(project.id, 3) is None


def test_templates_come_from_the_seed(connection):
    repo = ProjectRepository(connection)
    codes = [t["code"] for t in repo.list_templates()]
    assert "village" in codes
    assert len(repo.template_scene("village")) >= 5
    assert repo.template_scene("missing") is None


def test_a_full_run_updates_stats_and_scores(connection, user, project):
    plays = PlayRepository(connection)
    run_id = plays.start(project.id, user.id, 0.5)
    assert plays.find_open(run_id, project.id, user.id)["difficulty"] == 0.5
    assert plays.finish(run_id, RUN) is True
    assert plays.finish(run_id, RUN) is False  # a run is closed only once
    plays.add_to_player_stats(user.id, RUN)
    plays.add_to_player_stats(user.id, RUN)
    plays.add_high_score(project.id, user.id, 50)
    plays.record_event_summary(run_id, {"learned": False})
    assert plays.find_open(run_id, project.id, user.id) is None
    stats = plays.stats_of(user.id)
    assert (stats["games_played"], stats["games_won"], stats["total_score"]) == (2, 2, 100)
    assert plays.leaderboard(project.id) == [{"username": "game-test", "score": 50}]
    events = connection.execute(
        "select kind from play_events where play_session_id = %s order by id", (run_id,)
    ).fetchall()
    assert [e["kind"] for e in events] == ["coin", "summary"]


def test_ready_made_maps_are_seeded_and_valid(connection):
    from app.projects.schemas import SceneUpdate

    repo = ProjectRepository(connection)
    templates = {t["code"]: t for t in repo.list_templates()}
    for code in ("kenney-dungeon", "kenney-kingdom", "kenney-house", "kenney-city", "kenney-village"):
        scene = templates[code]["scene"]
        assert templates[code]["object_count"] == len(scene)
        SceneUpdate(scene=scene)  # the same rules as saving a scene: kinds, bounds, one player
        assert sum(1 for obj in scene if obj["kind"] == "player") == 1


def test_ai_model_upsert_and_samples(connection, user, project):
    models = AiModelRepository(connection)
    assert models.get(project.id)["samples_seen"] == 0
    model_id = models.save(project.id, {"difficulty": 0.6})
    assert models.save(project.id, {"difficulty": 0.7}) == model_id
    model = models.get(project.id)
    assert (model["samples_seen"], model["version"]) == (2, 2)
    assert difficulty_of(model) == 0.7
    models.add_sample(model_id, None, {"score": 1}, 0.5)
    request_id = models.record_request(project.id, user.id, "obstacles:2", "ok", "", 12)
    models.record_generation(request_id, [{"id": "w", "kind": "wall", "x": 1, "y": 1}], 0.7)


def test_choosing_a_difficulty_keeps_the_learned_parameters(connection, user, project):
    models = AiModelRepository(connection)
    models.set_difficulty(project.id, 0.2)  # no model yet: created with no samples
    assert (models.get(project.id)["samples_seen"], difficulty_of(models.get(project.id))) == (0, 0.2)
    models.save(project.id, {"difficulty": 0.5, "spread": 0.3})
    models.set_difficulty(project.id, 0.95)
    model = models.get(project.id)
    assert difficulty_of(model) == 0.95
    assert model["parameters"]["spread"] == 0.3
    assert model["samples_seen"] == 1


def test_settings_default_then_saved(connection, user):
    repo = SettingsRepository(connection)
    assert repo.get(user.id) == DEFAULTS
    saved = repo.save(user.id, {**DEFAULTS, "theme": "light"})
    assert saved["theme"] == "light"
    assert repo.save(user.id, {**DEFAULTS, "grid_size": 16})["grid_size"] == 16
    assert repo.get(user.id)["theme"] == "dark"


def test_catalog_lists_seeded_kinds_with_physics(connection):
    catalog = CatalogRepository(connection)
    kinds = {row["code"]: row for row in catalog.kinds()}
    assert {"box", "wall", "house", "coin", "enemy", "player"} <= set(kinds)
    assert kinds["wall"]["body_type"] == "static"
    assert kinds["box"]["movable"] is True
    assert [e["code"] for e in catalog.enemies()][:1] == ["slime"]
    assert any(t["code"] == "coin" for t in catalog.textures())


def test_achievements_are_unlocked_only_once(connection, user):
    from app.play.achievements import AchievementRepository

    repo = AchievementRepository(connection)
    assert repo.unlock(user.id, []) == []
    assert repo.unlock(user.id, ["first-coin", "first-win", "not-real"]) == ["first-coin", "first-win"]
    assert repo.unlock(user.id, ["first-coin"]) == []
    assert [a["code"] for a in repo.of_user(user.id)] == ["first-coin", "first-win"]


def test_profile_repository_round_trip(connection, user):
    from app.profile.router import ProfileRepository

    repo = ProfileRepository(connection)
    assert repo.get(user.id)["bio"] == ""
    repo.save(user.id, {"display_name": "Chucho", "avatar_url": "", "bio": "hola", "country": "CO"})
    assert repo.get(user.id)["display_name"] == "Chucho"


def test_maintenance_purge_runs_on_the_real_schema(connection):
    from app.maintenance import purge

    counts = purge(connection)
    assert set(counts) == {"revoked_access_tokens", "refresh_tokens", "login_attempts", "sessions"}


def test_characters_are_seeded_with_physics_textures_and_lines(connection):
    catalog = CatalogRepository(connection)
    kinds = {row["code"]: row for row in catalog.kinds()}
    for code in ("villager", "knight", "wizard", "ally", "guard"):
        assert kinds[code]["category"] == "character"
        assert kinds[code]["body_type"] == "dynamic"
        assert kinds[code]["hostile"] is False
    assert {t["code"] for t in catalog.textures()} >= {"villager", "knight", "wizard", "ally", "guard"}
    said = {row["kind"] for row in catalog.character_lines()}
    assert said == {"villager", "knight", "wizard", "ally", "guard"}


def test_new_enemies_items_and_obstacles_are_seeded(connection):
    catalog = CatalogRepository(connection)
    kinds = {row["code"]: row for row in catalog.kinds()}
    for code in ("bat", "spider", "ghost", "brute"):
        assert kinds[code]["hostile"] is True and kinds[code]["category"] == "enemy"
    for code in ("potion", "sword", "axe", "wand", "bow"):
        assert kinds[code]["collectible"] is True
    assert kinds["chest"]["body_type"] == "static"
    assert kinds["barrel"]["movable"] is True
    assert {"spider", "ghost", "brute"} <= {e["code"] for e in catalog.enemies()}


def test_every_table_refuses_rows_to_anyone_but_the_api(connection):
    """Row level security is on everywhere (migration 091): a hosted Postgres's own
    REST API (Supabase's anon and authenticated roles) cannot read or write the data."""
    open_tables = connection.execute(
        "select tablename from pg_tables where schemaname = 'public' and not rowsecurity"
    ).fetchall()
    assert [row["tablename"] for row in open_tables] == []


def test_admin_balance_and_creations_round_trip(connection, user):
    from app.admin.repository import AdminRepository
    admin = AdminRepository(connection)
    assert admin.balance(user.id) == {"heroes": {}, "enemies": {}}
    saved = admin.save_balance(user.id, {"knight": {"health": 9, "damage": 3}}, {"brute": {"health": 20, "damage": 4}})
    assert admin.balance(user.id) == saved
    values = {"category": "enemy", "base_kind": "brute", "name": "Ogro de hielo", "tint": "#7fd4ff",
              "health": 12, "damage": 3, "speed": 50, "value": 0}
    orc = admin.create(user.id, values)
    assert admin.count(user.id) == 1
    assert admin.update(user.id, orc["id"], {**values, "name": "Ogro de fuego"})["name"] == "Ogro de fuego"
    assert ProjectRepository(connection).creation_kinds(user.id, [orc["id"], 999999]) == {orc["id"]: "brute"}
    other = UserRepository(connection).create("other-admin", "other-admin@example.com", b"\x01" * 16, b"\x02" * 64)
    assert admin.creations(other.id) == []
    assert admin.update(other.id, orc["id"], values) is None
    assert admin.delete(other.id, orc["id"]) is False
    assert ProjectRepository(connection).creation_kinds(other.id, [orc["id"]]) == {}
    assert admin.delete(user.id, orc["id"]) is True
    assert admin.creations(user.id) == []


def test_a_scene_object_keeps_its_creation(connection, user):
    from app.admin.repository import AdminRepository
    orc = AdminRepository(connection).create(user.id, {"category": "enemy", "base_kind": "brute", "name": "Ogro",
                                                       "tint": "#ffffff", "health": 9, "damage": 2, "speed": 40, "value": 0})
    repo = ProjectRepository(connection)
    created = repo.create(user.id, "lvl", [])
    updated = repo.update_scene(created.id, user.id, [{"id": "o", "kind": "brute", "x": 5, "y": 5, "variant": orc["id"]}])
    assert updated.scene[0]["variant"] == orc["id"]
