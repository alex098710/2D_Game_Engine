import httpx

from app.auth.service_token import ServiceTokenIssuer


class AiServiceError(Exception):
    """The AI service could not be reached or answered with an error."""


class AiServiceClient:
    """The backend's only way to talk to the separate AI service.

    Every call carries a fresh service token (a JWT signed with the shared
    AI_SERVICE_KEY, valid for one minute). The frontend never reaches the AI
    service directly.
    """

    def __init__(self, base_url: str, service_key: str, transport=None, timeout: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._tokens = ServiceTokenIssuer(service_key)
        self._transport = transport
        # Generous timeout: a sleeping free-tier service needs time to wake up.
        self._timeout = timeout

    def _post(self, path: str, body: dict) -> dict:
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}{path}",
                    json=body,
                    headers={"Authorization": f"Bearer {self._tokens.issue()}"},
                )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("reply is not an object")
            return data
        except (httpx.HTTPError, ValueError) as error:
            raise AiServiceError(f"AI service call failed: {type(error).__name__}") from error

    def generate(self, prompt: str, scene: list | None = None) -> list:
        """Objects described by a natural-language prompt."""
        data = self._post("/generate", {"prompt": prompt, "scene": scene or []})
        return self._objects(data)

    def edit(self, prompt: str, scene: list | None = None) -> tuple:
        """(objects to add, ids to remove) for a request like "borra los enemigos y pon 3 monedas"."""
        data = self._post("/generate", {"prompt": prompt, "scene": scene or []})
        removed = data.get("removed", [])
        if not isinstance(removed, list) or not all(isinstance(i, str) for i in removed):
            raise AiServiceError("AI service call failed: invalid removed ids")
        return self._objects(data), removed

    def obstacles(self, model: dict, scene: list, count: int) -> dict:
        """New obstacles chosen by the learned model: {"objects", "difficulty"}."""
        data = self._post("/obstacles", {"model": model, "scene": scene, "count": count})
        self._objects(data)
        return data

    def learn(self, model: dict, run: dict) -> dict:
        """Update the model with one finished run: {"model", "reward", "difficulty"}."""
        data = self._post("/learn", {"model": model, "run": run})
        if not isinstance(data.get("model"), dict):
            raise AiServiceError("AI service call failed: missing model")
        return data

    @staticmethod
    def _objects(data: dict) -> list:
        objects = data.get("objects")
        if not isinstance(objects, list):
            raise AiServiceError("AI service call failed: missing objects")
        return objects
