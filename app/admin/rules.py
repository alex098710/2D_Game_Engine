"""What the admin panel of an account may change, and within which limits.

The frontend has the same lists (game/balance.ts); both check the numbers.
"""
from app.projects.world import ENEMY_KINDS

# Every hero of the hero select, with its own health and the damage of its weapon.
HERO_DEFAULTS = {
    "knight": {"health": 6, "damage": 1},
    "wizard": {"health": 4, "damage": 2},
    "archer": {"health": 5, "damage": 1},
    "barbarian": {"health": 7, "damage": 2},
    "rogue": {"health": 4, "damage": 1},
    "viking": {"health": 8, "damage": 2},
    "lancer": {"health": 6, "damage": 2},
    "druid": {"health": 5, "damage": 1},
    # Soldiers of the blue army: they fight with firearms.
    "soldier": {"health": 6, "damage": 2},
    "commando": {"health": 5, "damage": 1},
    "warrior": {"health": 7, "damage": 3},
}
HERO_IDS = tuple(HERO_DEFAULTS)

# Objects a player can make their own version of; the value is what "value" means.
OBJECT_BASES = {
    "potion": "heal", "medkit": "heal", "spike": "damage", "explosive": "damage",
    "chest": None, "coin": None, "box": None, "barrel": None, "rock": None, "tree": None, "bush": None,
}

HERO_HEALTH = (1, 20)
HERO_DAMAGE = (1, 10)
ENEMY_HEALTH = (1, 99)
ENEMY_DAMAGE = (0, 10)
SPEED = (0, 400)
VALUE = (0, 20)
MAX_CREATIONS = 60


def base_kinds(category: str) -> tuple:
    if category == "hero":
        return HERO_IDS
    if category == "enemy":
        return ENEMY_KINDS
    return tuple(OBJECT_BASES)
