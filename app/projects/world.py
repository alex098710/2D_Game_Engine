"""Shared rules of the game world. The frontend and the AI service use the same values."""

WORLD_WIDTH = 1600
WORLD_HEIGHT = 960
TILE_SIZE = 32

# Kinds the editor can place. 'player' is the spawn point (at most one per scene).
OBJECT_KINDS = (
    "player", "box", "wall", "house", "tree", "spike", "coin", "enemy", "villager", "knight", "wizard",
    # more enemies
    "bat", "spider", "ghost", "brute",
    # items: a chest drops one of the others when opened
    "chest", "potion", "sword", "axe", "wand", "bow",
    # more obstacles
    "barrel", "fence", "bush",
    # the weapons of the newer heroes
    "dagger", "hammer", "spear", "staff",
    # ground: a road or stone tile drawn under everything (no body), for towns and cities
    "path",
    # terrain: water blocks walking; sand and bridges are ground
    "water", "sand", "bridge",
    # enemies that shoot (dark archer, necromancer), a boss, a mimic and rats
    "marksman", "necromancer", "demon", "mimic", "rat",
    # war: soldiers and machines of the red army, the blue army's people, defences and ground
    "soldier", "grenadier", "tank", "artillery", "ally", "sandbag", "barricade", "hedgehog", "bunker", "tower",
    "flag", "banner", "rock", "road", "medkit", "legionary", "captain", "guard",
    # firearms the hero can pick up, and the powder keg that explodes
    "pistol", "rifle", "shotgun", "smg", "sniper", "launcher", "grenade", "explosive",
    # the Western town: buildings, covers, ground and the bandit
    "saloon", "cabin", "wagon", "hay", "crates", "trough", "cactus", "lamp", "boardwalk", "dirt", "bandit",
    # the industrial arena: floor, walls, covers, the reactor and two enemies
    "metalfloor", "hazard", "steelwall", "container", "pipes", "reactor", "beacon", "barrier", "turret", "drone",
)
ENEMY_KINDS = (
    "enemy", "bat", "spider", "ghost", "brute", "marksman", "necromancer", "demon", "mimic", "rat",
    "soldier", "grenadier", "tank", "artillery", "legionary", "captain", "bandit", "turret", "drone",
)
ITEM_KINDS = (
    "chest", "potion", "sword", "axe", "wand", "bow", "dagger", "hammer", "spear", "staff",
    "medkit", "pistol", "rifle", "shotgun", "smg", "sniper", "launcher", "grenade",
)
# 2D characters: friendly people that walk around and talk to the player.
CHARACTER_KINDS = ("villager", "knight", "wizard", "ally", "guard")
# Big enough for a whole city of 50 x 30 tiles with its roads.
MAX_OBJECTS = 1500

# Points the game gives for each coin and for defeating each kind of enemy.
# Same values as the frontend (ScoreCounter.ts and combat.ts): the backend uses
# them to reject runs that claim more points than the level can give.
COIN_POINTS = 1
ENEMY_POINTS = {
    "enemy": 5, "bat": 3, "spider": 4, "ghost": 6, "brute": 15,
    "marksman": 7, "necromancer": 9, "demon": 40, "mimic": 8, "rat": 2,
    "soldier": 7, "grenadier": 8, "tank": 35, "artillery": 10, "legionary": 6, "captain": 16, "bandit": 7, "turret": 10, "drone": 5,
}
