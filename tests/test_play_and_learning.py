from fastapi.testclient import TestClient

from app.ai_learning.dependencies import get_ai_models, get_optional_ai_client
from app.auth.dependencies import current_user
from app.auth.user import User
from app.main import app
from app.play.router import get_achievements, get_plays
from app.projects.router import get_ai_client, get_repository
from tests.fakes_game import FakeAchievementRepository, FakeAiModelRepository, FakeLearningAi, FakePlayRepository
from tests.test_projects import FakeProjectRepository

# The level every test plays: six coins, a slime (5 points) and a brute (15 points).
SCENE = [{"id": f"c{i}", "kind": "coin", "x": 40 + 40 * i, "y": 40} for i in range(6)] + [
    {"id": "e1", "kind": "enemy", "x": 400, "y": 300},
    {"id": "b1", "kind": "brute", "x": 600, "y": 300},
]

# Best possible run of SCENE: 6 coins (6 points) + both enemies (20 points).
RUN = {
    "outcome": "won", "score": 26, "coins_collected": 6, "coins_total": 6,
    "enemies_defeated": 2, "damage_taken": 1, "deaths": 0, "duration_ms": 45000,
    "events": [{"kind": "coin", "x": 10, "y": 20, "at_ms": 1000}],
}


class World:
    def __init__(self, ai=None, user_id=1):
        self.projects = FakeProjectRepository()
        self.plays = FakePlayRepository()
        self.models = FakeAiModelRepository()
        self.achievements = FakeAchievementRepository()
        app.dependency_overrides[get_achievements] = lambda: self.achievements
        self.ai = ai
        self.user = User(user_id, "jesus", "j@example.com", b"s", b"h")
        app.dependency_overrides[get_repository] = lambda: self.projects
        app.dependency_overrides[get_plays] = lambda: self.plays
        app.dependency_overrides[get_ai_models] = lambda: self.models
        app.dependency_overrides[get_optional_ai_client] = lambda: self.ai
        app.dependency_overrides[get_ai_client] = lambda: self.ai
        app.dependency_overrides[current_user] = lambda: self.user
        self.client = TestClient(app)
        self.project_id = self.projects.create(user_id, "level", SCENE).id


def teardown_function():
    app.dependency_overrides.clear()


def play(world, run=RUN):
    run_id = world.client.post(f"/projects/{world.project_id}/plays").json()["id"]
    return world.client.post(f"/projects/{world.project_id}/plays/{run_id}/finish", json=run)


def test_start_run_returns_an_id_and_the_default_difficulty():
    world = World()
    response = world.client.post(f"/projects/{world.project_id}/plays")
    assert response.status_code == 201
    assert response.json() == {"id": 1, "difficulty": 0.5}


def test_finish_run_without_ai_still_saves_everything():
    world = World(ai=None)
    response = play(world)
    assert response.status_code == 200
    assert response.json()["learned"] is False
    assert response.json()["difficulty"] == 0.5
    assert world.plays.runs[1]["result"].score == 26
    assert world.plays.stats[1]["games_played"] == 1
    assert world.plays.scores == [(world.project_id, 1, 26)]


def test_finish_run_lets_the_ai_learn_and_raises_difficulty_after_a_win():
    world = World(ai=FakeLearningAi())
    body = play(world).json()
    assert body["learned"] is True
    assert round(body["difficulty"], 2) == 0.6
    assert world.models.get(world.project_id)["samples_seen"] == 1
    assert world.ai.learned[0][1]["outcome"] == "won"
    assert "events" not in world.ai.learned[0][1]
    next_run = world.client.post(f"/projects/{world.project_id}/plays").json()
    assert round(next_run["difficulty"], 2) == 0.6


def test_ai_failure_does_not_lose_the_run():
    world = World(ai=FakeLearningAi(fail=True))
    response = play(world)
    assert response.status_code == 200
    assert response.json()["learned"] is False
    assert world.plays.runs[1]["result"] is not None


def test_a_run_cannot_be_finished_twice():
    world = World()
    run_id = world.client.post(f"/projects/{world.project_id}/plays").json()["id"]
    url = f"/projects/{world.project_id}/plays/{run_id}/finish"
    assert world.client.post(url, json=RUN).status_code == 200
    assert world.client.post(url, json=RUN).status_code == 404


def test_invalid_run_numbers_are_rejected():
    world = World()
    run_id = world.client.post(f"/projects/{world.project_id}/plays").json()["id"]
    url = f"/projects/{world.project_id}/plays/{run_id}/finish"
    assert world.client.post(url, json={**RUN, "coins_collected": 9}).status_code == 422
    assert world.client.post(url, json={**RUN, "outcome": "draw"}).status_code == 422
    assert world.client.post(url, json={**RUN, "score": -1}).status_code == 422


def test_another_users_project_cannot_be_played():
    world = World()
    other = world.projects.create(2, "not mine", []).id
    assert world.client.post(f"/projects/{other}/plays").status_code == 404
    assert world.client.get(f"/projects/{other}/leaderboard").status_code == 404


def test_leaderboard_and_my_stats():
    world = World()
    play(world, {**RUN, "score": 20})
    play(world)
    board = world.client.get(f"/projects/{world.project_id}/leaderboard").json()
    assert [row["score"] for row in board] == [26, 20]
    assert world.client.get("/me/stats").json()["best_score"] == 26


def test_my_stats_before_playing_are_zero():
    assert World().client.get("/me/stats").json()["games_played"] == 0


def test_learned_obstacles_are_added_to_the_scene():
    world = World(ai=FakeLearningAi())
    response = world.client.post(f"/projects/{world.project_id}/ai/obstacles", json={"count": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["added"] == 3
    assert [obj["kind"] for obj in body["scene"]] == ["coin"] * 6 + ["enemy", "brute"] + ["wall"] * 3
    assert world.models.requests == [(world.project_id, "obstacles:3", "ok")]
    assert world.models.generations[0][1] == 3


def test_obstacle_count_is_limited():
    world = World(ai=FakeLearningAi())
    url = f"/projects/{world.project_id}/ai/obstacles"
    assert world.client.post(url, json={"count": 0}).status_code == 422
    assert world.client.post(url, json={"count": 31}).status_code == 422


def test_obstacles_when_the_ai_is_down_return_502():
    world = World(ai=FakeLearningAi(fail=True))
    response = world.client.post(f"/projects/{world.project_id}/ai/obstacles", json={"count": 2})
    assert response.status_code == 502


def test_model_endpoint_shows_what_was_learned():
    world = World(ai=FakeLearningAi())
    assert world.client.get(f"/projects/{world.project_id}/ai/model").json()["samples_seen"] == 0
    play(world)
    model = world.client.get(f"/projects/{world.project_id}/ai/model").json()
    assert model["samples_seen"] == 1
    assert round(model["difficulty"], 2) == 0.6


def test_finishing_runs_unlocks_achievements_once():
    world = World()
    first = play(world).json()["achievements"]
    assert first == ["first-coin", "coin-hoarder", "first-win"]
    perfect = {**RUN, "damage_taken": 0}
    assert play(world, perfect).json()["achievements"] == ["untouchable"]
    assert play(world, perfect).json()["achievements"] == []
    codes = [a["code"] for a in world.client.get("/me/achievements").json()]
    assert codes == ["first-coin", "coin-hoarder", "first-win", "untouchable"]


def test_a_run_that_does_not_match_the_level_is_rejected():
    world = World()
    rejected = [
        {**RUN, "coins_total": 3, "coins_collected": 3, "score": 3},  # the level has 6 coins
        {**RUN, "enemies_defeated": 3},  # the level has 2 enemies
        {**RUN, "score": 27},  # 6 coins + slime + brute = 26 at most
        {**RUN, "outcome": "won", "coins_collected": 5, "score": 25},  # a coin is missing
    ]
    for run in rejected:
        response = play(world, run)
        assert response.status_code == 422, run
        # The reason is not told: a cheater learns nothing about the checks.
        assert response.json()["detail"] == "Run rejected"
    assert world.plays.scores == []
    assert world.plays.stats == {}


def test_a_lost_run_with_some_coins_is_accepted():
    world = World()
    lost = {**RUN, "outcome": "lost", "coins_collected": 2, "enemies_defeated": 1, "score": 7, "deaths": 1}
    assert play(world, lost).status_code == 200


def test_the_score_bound_uses_the_most_valuable_enemies():
    world = World()
    # One enemy defeated: at best the brute, 15 points, plus the coins.
    assert play(world, {**RUN, "outcome": "lost", "enemies_defeated": 1, "score": 21}).status_code == 200
    assert play(world, {**RUN, "outcome": "lost", "enemies_defeated": 1, "score": 22}).status_code == 422


def test_the_run_is_saved_before_the_ai_is_called():
    world = World(ai=FakeLearningAi())
    play(world)
    assert world.plays.commits == 1


def test_two_requests_finishing_the_same_run_count_it_once():
    class Racing(FakePlayRepository):
        """find_open always answers 'open', like two requests checking at the same time."""

        def find_open(self, play_id, project_id, player_id):
            return {"id": play_id, "difficulty": 0.5}

    world = World()
    world.plays = Racing()
    app.dependency_overrides[get_plays] = lambda: world.plays
    run_id = world.client.post(f"/projects/{world.project_id}/plays").json()["id"]
    url = f"/projects/{world.project_id}/plays/{run_id}/finish"
    assert world.client.post(url, json=RUN).status_code == 200
    assert world.client.post(url, json=RUN).status_code == 404
    assert world.plays.stats[1]["games_played"] == 1
    assert len(world.plays.scores) == 1


def test_the_player_can_choose_one_of_four_difficulties():
    world = World(ai=FakeLearningAi())
    assert world.client.get(f"/projects/{world.project_id}/ai/model").json()["level"] == "medium"
    for level, value in [("easy", 0.2), ("medium", 0.45), ("hard", 0.7), ("extreme", 0.95)]:
        model = world.client.put(f"/projects/{world.project_id}/ai/difficulty", json={"level": level}).json()
        assert model["level"] == level
        assert model["difficulty"] == value
    # The next run starts at the chosen difficulty.
    assert world.client.post(f"/projects/{world.project_id}/plays").json()["difficulty"] == 0.95


def test_choosing_a_difficulty_keeps_what_was_learned():
    world = World(ai=FakeLearningAi())
    play(world)
    model = world.client.put(f"/projects/{world.project_id}/ai/difficulty", json={"level": "easy"}).json()
    assert model["samples_seen"] == 1
    assert model["difficulty"] == 0.2


def test_an_unknown_difficulty_or_someone_elses_level_is_rejected():
    world = World()
    assert world.client.put(f"/projects/{world.project_id}/ai/difficulty", json={"level": "imposible"}).status_code == 422
    other = World(user_id=2)
    other.projects = world.projects
    app.dependency_overrides[get_repository] = lambda: world.projects
    assert other.client.put(f"/projects/{world.project_id}/ai/difficulty", json={"level": "easy"}).status_code == 404
