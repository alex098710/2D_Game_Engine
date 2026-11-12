"""In-memory stand-ins for the play, AI-model and settings repositories."""
from app.ai_learning.repository import DEFAULT_DIFFICULTY
from app.settings.repository import DEFAULTS


class FakePlayRepository:

    def __init__(self):
        self.runs = {}
        self.stats = {}
        self.scores = []
        self.summaries = []
        self.commits = 0
        self._next_id = 1

    def start(self, project_id, player_id, difficulty):
        run_id = self._next_id
        self._next_id += 1
        self.runs[run_id] = {"project_id": project_id, "player_id": player_id,
                             "difficulty": difficulty, "result": None}
        return run_id

    def find_open(self, play_id, project_id, player_id):
        run = self.runs.get(play_id)
        if run and run["project_id"] == project_id and run["player_id"] == player_id and run["result"] is None:
            return {"id": play_id, "difficulty": run["difficulty"]}
        return None

    def finish(self, play_id, result):
        if self.runs[play_id]["result"] is not None:
            return False
        self.runs[play_id]["result"] = result
        return True

    def commit(self):
        self.commits += 1

    def add_to_player_stats(self, user_id, result):
        stats = self.stats.setdefault(user_id, {"games_played": 0, "best_score": 0, "enemies_defeated": 0})
        stats["games_played"] += 1
        stats["enemies_defeated"] += result.enemies_defeated
        stats["best_score"] = max(stats["best_score"], result.score)

    def add_high_score(self, project_id, user_id, score):
        self.scores.append((project_id, user_id, score))

    def leaderboard(self, project_id, limit=10):
        rows = [{"username": f"user{u}", "score": s} for p, u, s in self.scores if p == project_id]
        return sorted(rows, key=lambda r: -r["score"])[:limit]

    def stats_of(self, user_id):
        return self.stats.get(user_id)

    def record_event_summary(self, play_id, details):
        self.summaries.append((play_id, details))


class FakeAiModelRepository:

    def __init__(self):
        self.models = {}
        self.samples = []
        self.requests = []
        self.generations = []

    def get(self, project_id):
        return self.models.get(project_id, {"id": None, "parameters": {}, "samples_seen": 0, "version": 0})

    def save(self, project_id, parameters):
        current = self.get(project_id)
        self.models[project_id] = {"id": project_id, "parameters": parameters,
                                   "samples_seen": current["samples_seen"] + 1,
                                   "version": current["version"] + 1}
        return project_id

    def add_sample(self, model_id, play_id, features, reward):
        self.samples.append((model_id, play_id, reward))

    def record_request(self, project_id, user_id, prompt, status, error="", duration_ms=0):
        self.requests.append((project_id, prompt, status))
        return len(self.requests)

    def record_generation(self, request_id, objects, difficulty):
        self.generations.append((request_id, len(objects), difficulty))


class FakeSettingsRepository:

    def __init__(self):
        self.rows = {}

    def get(self, user_id):
        return dict(self.rows.get(user_id, DEFAULTS))

    def save(self, user_id, settings):
        self.rows[user_id] = dict(settings)
        return dict(settings)


class FakeLearningAi:
    """AI client double: learn() raises difficulty after a win, obstacles() adds walls."""

    def __init__(self, fail=False):
        self.fail = fail
        self.learned = []
        self.obstacle_calls = []

    def _maybe_fail(self):
        if self.fail:
            from app.ai_client import AiServiceError
            raise AiServiceError("down")

    def learn(self, model, run):
        self._maybe_fail()
        self.learned.append((model, run))
        difficulty = model.get("difficulty", DEFAULT_DIFFICULTY) + (0.1 if run["outcome"] == "won" else -0.1)
        return {"model": {"difficulty": difficulty}, "reward": 1.0, "difficulty": difficulty}

    def obstacles(self, model, scene, count):
        self._maybe_fail()
        self.obstacle_calls.append((model, len(scene), count))
        objects = [{"id": f"wall-{i}", "kind": "wall", "x": 100 + 32 * i, "y": 200} for i in range(count)]
        return {"objects": objects, "difficulty": model.get("difficulty", DEFAULT_DIFFICULTY)}

    def edit(self, prompt, scene=None):
        return self.generate(prompt, scene), []

    def generate(self, prompt, scene=None):
        self._maybe_fail()
        return []


class FakeAchievementRepository:

    def __init__(self):
        self.owned = {}

    def unlock(self, user_id, codes):
        owned = self.owned.setdefault(user_id, [])
        new = [code for code in codes if code not in owned]
        owned.extend(new)
        return new

    def of_user(self, user_id):
        from datetime import datetime, timezone
        return [{"code": c, "name": c, "description": "", "points": 10,
                 "unlocked_at": datetime.now(timezone.utc)} for c in self.owned.get(user_id, [])]
