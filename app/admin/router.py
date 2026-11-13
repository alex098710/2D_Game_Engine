"""The admin panel of each account.

/me/balance: the health and damage of every hero and enemy for this account.
/me/creations: heroes, enemies and objects this account created. A creation
starts from a base kind (its picture and behaviour) and has its own name,
colour and numbers. Everything here belongs to one account and is only ever
read or changed by it.
"""
import re
from typing import Dict, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from app.auth.dependencies import current_user
from app.auth.user import User
from app.database import database_connection
from app.projects.world import ENEMY_KINDS
from .repository import AdminRepository
from .rules import (
    ENEMY_DAMAGE, ENEMY_HEALTH, HERO_DAMAGE, HERO_HEALTH, HERO_IDS, MAX_CREATIONS, OBJECT_BASES, SPEED, VALUE,
    base_kinds,
)

router = APIRouter(prefix="/me", tags=["admin"])

_TINT = re.compile(r"^#[0-9a-f]{6}$")


def get_admin_repository(connection=Depends(database_connection)) -> AdminRepository:
    return AdminRepository(connection)


class Stats(BaseModel):
    health: int
    damage: int


class BalanceIn(BaseModel):
    heroes: Dict[str, Stats] = Field(default_factory=dict)
    enemies: Dict[str, Stats] = Field(default_factory=dict)

    @model_validator(mode="after")
    def known_and_in_range(self):
        for hero, stats in self.heroes.items():
            if hero not in HERO_IDS:
                raise ValueError(f"unknown hero {hero!r}")
            _check(stats.health, HERO_HEALTH, "health")
            _check(stats.damage, HERO_DAMAGE, "damage")
        for enemy, stats in self.enemies.items():
            if enemy not in ENEMY_KINDS:
                raise ValueError(f"unknown enemy {enemy!r}")
            _check(stats.health, ENEMY_HEALTH, "health")
            _check(stats.damage, ENEMY_DAMAGE, "damage")
        return self


def _check(value: int, limits: tuple, name: str) -> None:
    if not limits[0] <= value <= limits[1]:
        raise ValueError(f"{name} must be between {limits[0]} and {limits[1]}")


class CreationIn(BaseModel):
    category: Literal["hero", "enemy", "object"]
    base_kind: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=24)
    tint: str = "#ffffff"
    health: int = 0
    damage: int = 0
    speed: int = 0
    value: int = 0

    @field_validator("name")
    @classmethod
    def name_is_not_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("tint")
    @classmethod
    def tint_is_a_colour(cls, value: str) -> str:
        value = value.lower()
        if not _TINT.match(value):
            raise ValueError("tint must look like #3fa9ff")
        return value

    @model_validator(mode="after")
    def fits_its_category(self):
        if self.base_kind not in base_kinds(self.category):
            raise ValueError(f"{self.base_kind!r} cannot be the base of a {self.category}")
        if self.category == "hero":
            _check(self.health, HERO_HEALTH, "health")
            _check(self.damage, HERO_DAMAGE, "damage")
            _check(self.speed, (100, 300), "speed")
            self.value = 0
        elif self.category == "enemy":
            _check(self.health, ENEMY_HEALTH, "health")
            _check(self.damage, ENEMY_DAMAGE, "damage")
            _check(self.speed, SPEED, "speed")
            self.value = 0
        else:
            effect = OBJECT_BASES[self.base_kind]
            self.health = 0
            self.speed = 0
            _check(self.value, VALUE, "value")
            if effect is None:
                self.value = 0
            self.damage = 0
        return self


def creation_json(row: dict) -> dict:
    return {**row, "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat()}


@router.get("/balance")
def read_balance(repo: AdminRepository = Depends(get_admin_repository), user: User = Depends(current_user)):
    return repo.balance(user.id)


@router.put("/balance")
def save_balance(body: BalanceIn, repo: AdminRepository = Depends(get_admin_repository),
                 user: User = Depends(current_user)):
    heroes = {hero: stats.model_dump() for hero, stats in body.heroes.items()}
    enemies = {enemy: stats.model_dump() for enemy, stats in body.enemies.items()}
    return repo.save_balance(user.id, heroes, enemies)


@router.get("/creations")
def list_creations(repo: AdminRepository = Depends(get_admin_repository), user: User = Depends(current_user)):
    return [creation_json(row) for row in repo.creations(user.id)]


@router.post("/creations", status_code=201)
def create_creation(body: CreationIn, repo: AdminRepository = Depends(get_admin_repository),
                    user: User = Depends(current_user)):
    if repo.count(user.id) >= MAX_CREATIONS:
        raise HTTPException(status_code=422, detail=f"Puedes tener hasta {MAX_CREATIONS} creaciones")
    return creation_json(repo.create(user.id, body.model_dump()))


@router.put("/creations/{creation_id}")
def update_creation(creation_id: int, body: CreationIn, repo: AdminRepository = Depends(get_admin_repository),
                    user: User = Depends(current_user)):
    row = repo.update(user.id, creation_id, body.model_dump())
    if row is None:
        raise HTTPException(status_code=404, detail="Creation not found")
    return creation_json(row)


@router.delete("/creations/{creation_id}", status_code=204)
def delete_creation(creation_id: int, repo: AdminRepository = Depends(get_admin_repository),
                    user: User = Depends(current_user)):
    if not repo.delete(user.id, creation_id):
        raise HTTPException(status_code=404, detail="Creation not found")
    return Response(status_code=204)
