import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.ai_client import AiServiceClient, AiServiceError
from app.auth.dependencies import current_user
from app.auth.user import User
from app.projects.router import (
    append_objects,
    get_ai_client,
    get_repository,
    load_project,
    project_json,
    validate_generated,
)
from app.projects.schemas import ObstacleRequest
from .dependencies import get_ai_models
from .repository import DIFFICULTY_LEVELS, AiModelRepository, difficulty_of, level_of

router = APIRouter(prefix="/projects/{project_id}/ai", tags=["ai"])


class DifficultyRequest(BaseModel):
    level: Literal["easy", "medium", "hard", "extreme"]


def model_json(model: dict) -> dict:
    difficulty = difficulty_of(model)
    return {
        "samples_seen": model["samples_seen"],
        "version": model["version"],
        "difficulty": difficulty,
        "level": level_of(difficulty),
        "parameters": model["parameters"],
    }


@router.get("/model")
def get_model(project_id: int, repo=Depends(get_repository), models: AiModelRepository = Depends(get_ai_models),
              user: User = Depends(current_user)):
    """What the AI has learned so far for this level."""
    load_project(project_id, repo, user.id)
    return model_json(models.get(project_id))


@router.put("/difficulty")
def set_difficulty(project_id: int, body: DifficultyRequest, repo=Depends(get_repository),
                   models: AiModelRepository = Depends(get_ai_models), user: User = Depends(current_user)):
    """Choose Fácil, Medio, Difícil or Extremo; the AI keeps learning from that point."""
    load_project(project_id, repo, user.id)
    models.set_difficulty(project_id, DIFFICULTY_LEVELS[body.level])
    return model_json(models.get(project_id))


@router.post("/obstacles")
def add_learned_obstacles(
    project_id: int,
    body: ObstacleRequest,
    repo=Depends(get_repository),
    models: AiModelRepository = Depends(get_ai_models),
    user: User = Depends(current_user),
    ai_client: AiServiceClient = Depends(get_ai_client),
):
    """Let the learned model place new obstacles where players struggle least."""
    project = load_project(project_id, repo, user.id)
    model = models.get(project_id)
    repo.commit()  # do not hold the database while the AI answers
    started = time.monotonic()
    try:
        reply = ai_client.obstacles(model["parameters"], list(project.scene), body.count)
    except AiServiceError as error:
        raise HTTPException(status_code=502, detail="La IA no respondió, inténtalo de nuevo") from error
    objects = validate_generated(reply["objects"])
    scene = append_objects(project, objects)
    elapsed = int((time.monotonic() - started) * 1000)
    request_id = models.record_request(project_id, user.id, f"obstacles:{body.count}", "ok", "", elapsed)
    difficulty = float(reply.get("difficulty", difficulty_of(model)))
    models.record_generation(request_id, objects, difficulty)
    result = project_json(repo.update_scene(project_id, user.id, scene))
    result["difficulty"] = difficulty
    result["added"] = len(objects)
    return result
