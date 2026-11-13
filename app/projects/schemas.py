from typing import List, Literal

from pydantic import BaseModel, Field, field_validator

from .world import MAX_OBJECTS, OBJECT_KINDS, WORLD_HEIGHT, WORLD_WIDTH

ObjectKind = Literal[OBJECT_KINDS]

# Short names fit every list and title of the editor without being cut.
PROJECT_NAME_MAX = 30


class GameObjectIn(BaseModel):
    """One object of a scene. Coordinates must be inside the world."""

    id: str = Field(min_length=1, max_length=64)
    kind: ObjectKind
    x: float = Field(ge=0, le=WORLD_WIDTH)
    y: float = Field(ge=0, le=WORLD_HEIGHT)
    # Optional: the id of one of the owner's own creations based on this kind.
    variant: int | None = Field(default=None, ge=1)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=PROJECT_NAME_MAX)
    template: str | None = Field(default=None, max_length=40)

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class ProjectRename(ProjectCreate):
    template: None = None


class SceneUpdate(BaseModel):
    scene: List[GameObjectIn] = Field(max_length=MAX_OBJECTS)
    note: str = Field(default="", max_length=200)

    @field_validator("scene")
    @classmethod
    def ids_are_unique_and_one_player(cls, scene):
        ids = [obj.id for obj in scene]
        if len(ids) != len(set(ids)):
            raise ValueError("object ids must be unique")
        if sum(1 for obj in scene if obj.kind == "player") > 1:
            raise ValueError("a scene can have only one player")
        return scene


class AiRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)


class ObstacleRequest(BaseModel):
    count: int = Field(default=6, ge=1, le=30)
