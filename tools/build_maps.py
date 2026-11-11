"""Turns the grids in maps/kenney/ and maps/battle/ into a migration with the ready-made maps.

    python tools/build_maps.py      # writes the newest map migration (see MIGRATION below)

Each grid is 50 x 30 characters, one per tile of the world (see maps/README.md).
Before writing, every map is checked: exactly one player, no unknown characters,
and every chest reachable on foot from the player.
"""
import json
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_OBJECTS = 1500  # same as app/projects/world.py
COLUMNS, ROWS, TILE = 50, 30, 32
KINDS = {
    "#": "wall", "T": "tree", "b": "bush", "f": "fence", "B": "box", "R": "barrel", "^": "spike",
    "C": "chest", "v": "villager", "k": "knight", "z": "wizard", "e": "enemy", "a": "bat",
    "s": "spider", "O": "brute", "P": "player", "g": "ghost", "c": "coin", "p": "potion",
    "d": "dagger", "h": "hammer", "l": "spear", "t": "staff", "=": "path",
    "w": "water", "_": "bridge", ":": "sand",
    "m": "marksman", "n": "necromancer", "D": "demon", "M": "mimic", "r": "rat",
    # war (maps/battle/)
    "S": "soldier", "G": "grenadier", "K": "tank", "A": "artillery", "L": "legionary", "Q": "captain",
    "y": "ally", "u": "guard", "~": "sandbag", "|": "barricade", "x": "hedgehog", "H": "bunker",
    "W": "tower", "F": "flag", "!": "banner", "o": "rock", "-": "road", "+": "medkit", "X": "explosive",
    "1": "pistol", "2": "rifle", "3": "shotgun", "4": "smg", "5": "sniper", "6": "launcher", "7": "grenade",
}
SOLID = {"wall", "tree", "bush", "fence", "water", "sandbag", "barricade", "hedgehog", "bunker", "tower",
         "flag", "banner", "rock", "explosive"}
# Ground characters: what goes under a person or an item standing among them.
GROUNDS = {"=": "path", "-": "road"}
# Things that can stand on a road: when most of their neighbours are road, a
# road tile is put under them too, so people and coins don't sit on a hole of grass.
ON_ROAD = {"villager", "knight", "wizard", "enemy", "bat", "spider", "ghost", "brute", "coin", "potion",
           "chest", "dagger", "hammer", "spear", "staff", "box", "barrel", "player",
           "marksman", "necromancer", "demon", "mimic", "rat",
           "soldier", "grenadier", "tank", "artillery", "legionary", "captain", "ally", "guard", "medkit",
           "pistol", "rifle", "shotgun", "smg", "sniper", "launcher", "grenade"}

# Migrations are history: once applied in production they never change. 088 and
# 089 seeded the first maps; the newest migration (MIGRATION) re-seeds every map
# with "do update", so edit the grids, point MIGRATION at a new number and run this.
MIGRATION = "092_war_kinds_and_battle_maps.sql"

MAPS = [
    ("kenney-dungeon", "kenney/dungeon.txt", "Mazmorra (Kenney)",
     "Mapa de ejemplo del pack Tiny Dungeon de Kenney (CC0): salas, vías y enemigos"),
    ("kenney-kingdom", "kenney/kingdom.txt", "Reino (Kenney)",
     "Castillo con foso, río, aldea y bosque del 1-Bit Pack de Kenney (CC0); un demonio guarda el castillo"),
    ("kenney-house", "kenney/house.txt", "Casa (Kenney)",
     "Interior de una casa con sus habitantes, del 1-Bit Pack de Kenney (CC0)"),
    ("kenney-city", "kenney/city.txt", "Ciudad (Kenney)",
     "Una ciudad con calles, aceras, edificios, coches, un parque y un lago, del 1-Bit Pack de Kenney (CC0); "
     "recoge las monedas y limpia las calles de monstruos y arqueros"),
    ("kenney-village", "kenney/village.txt", "Aldea (Kenney)",
     "Aldea con casas, lago, bosque, campamento y cementerio, del Roguelike/RPG pack de Kenney (CC0); "
     "un demonio acampa al noreste"),
    ("battle-front", "battle/front.txt", "Frente de batalla",
     "Dos campamentos separados por un río: tu base azul al oeste y el ejército rojo al este, con "
     "artillería, granaderos y un tanque. Cruza los puentes y vuela sus barriles"),
    ("battle-siege", "battle/siege.txt", "Asedio al búnker",
     "Una fortaleza de sacos terreros con torres, artillería y un tanque en el centro; "
     "haz explotar los barriles para abrir una brecha"),
]

# Kinds added with this migration: terrain and the enemies that shoot.
NEW_KINDS_SQL = """-- War: the red army (enemies), the blue army (friendly people), defences,
-- the road, the medkit, the firearms the hero can pick up and the powder keg.
insert into object_kinds (code, name, category, solid, movable, collectible, hostile) values
    ('soldier',   'Fusilero',          'enemy',       true,  true,  false, true),
    ('grenadier', 'Granadero',         'enemy',       true,  true,  false, true),
    ('tank',      'Tanque',            'enemy',       true,  true,  false, true),
    ('artillery', 'Artillería',        'enemy',       true,  false, false, true),
    ('legionary', 'Legionario',        'enemy',       true,  true,  false, true),
    ('captain',   'Capitán',           'enemy',       true,  true,  false, true),
    ('ally',      'Soldado aliado',    'decoration',  true,  true,  false, false),
    ('guard',     'Guardia',           'decoration',  true,  true,  false, false),
    ('sandbag',   'Sacos terreros',    'obstacle',    true,  false, false, false),
    ('barricade', 'Barricada',         'obstacle',    true,  false, false, false),
    ('hedgehog',  'Erizo antitanque',  'obstacle',    true,  false, false, false),
    ('rock',      'Colina',            'obstacle',    true,  false, false, false),
    ('bunker',    'Búnker',            'building',    true,  false, false, false),
    ('tower',     'Torre de vigía',    'building',    true,  false, false, false),
    ('flag',      'Bandera',           'decoration',  true,  false, false, false),
    ('banner',    'Estandarte rojo',   'decoration',  true,  false, false, false),
    ('road',      'Carretera',         'decoration',  false, false, false, false),
    ('medkit',    'Botiquín',          'collectible', false, false, true,  false),
    ('pistol',    'Pistola',           'collectible', false, false, true,  false),
    ('rifle',     'Fusil',             'collectible', false, false, true,  false),
    ('shotgun',   'Escopeta',          'collectible', false, false, true,  false),
    ('smg',       'Subfusil',          'collectible', false, false, true,  false),
    ('sniper',    'Francotirador',     'collectible', false, false, true,  false),
    ('launcher',  'Lanzacohetes',      'collectible', false, false, true,  false),
    ('grenade',   'Granadas',          'collectible', false, false, true,  false),
    ('explosive', 'Barril explosivo',  'obstacle',    true,  false, false, true)
on conflict (code) do nothing;

insert into object_physics (kind, body_type, material_id, mass, drag, immovable)
select k.kind, k.body_type, m.id, k.mass, k.drag, k.immovable
from (values
    ('soldier',   'dynamic', 'flesh', 1.5,  200, false),
    ('grenadier', 'dynamic', 'flesh', 1.5,  200, false),
    ('tank',      'dynamic', 'stone', 14.0, 300, false),
    ('artillery', 'static',  'stone', 1.0,  0,   true),
    ('legionary', 'dynamic', 'flesh', 1.5,  200, false),
    ('captain',   'dynamic', 'flesh', 4.0,  300, false),
    ('ally',      'dynamic', 'flesh', 1.0,  300, false),
    ('guard',     'dynamic', 'flesh', 1.0,  300, false),
    ('sandbag',   'static',  'stone', 1.0,  0,   true),
    ('barricade', 'static',  'stone', 1.0,  0,   true),
    ('hedgehog',  'static',  'stone', 1.0,  0,   true),
    ('rock',      'static',  'stone', 1.0,  0,   true),
    ('bunker',    'static',  'stone', 1.0,  0,   true),
    ('tower',     'static',  'stone', 1.0,  0,   true),
    ('flag',      'static',  'wood',  1.0,  0,   true),
    ('banner',    'static',  'wood',  1.0,  0,   true),
    ('road',      'none',    'stone', 1.0,  0,   true),
    ('medkit',    'none',    'wood',  1.0,  0,   true),
    ('pistol',    'none',    'stone', 1.0,  0,   true),
    ('rifle',     'none',    'stone', 1.0,  0,   true),
    ('shotgun',   'none',    'stone', 1.0,  0,   true),
    ('smg',       'none',    'stone', 1.0,  0,   true),
    ('sniper',    'none',    'stone', 1.0,  0,   true),
    ('launcher',  'none',    'stone', 1.0,  0,   true),
    ('grenade',   'none',    'stone', 1.0,  0,   true),
    ('explosive', 'static',  'wood',  1.0,  0,   true)
) as k (kind, body_type, material, mass, drag, immovable)
join physics_materials m on m.code = k.material
on conflict (kind) do nothing;

insert into textures (pack_id, code, kind, file_path, width, height, frames)
select p.id, t.code, t.code, 'textures/' || t.code || '.png', 32, 32, 1
from texture_packs p
cross join (values
    ('soldier'), ('grenadier'), ('tank'), ('artillery'), ('legionary'), ('captain'), ('ally'), ('guard'),
    ('sandbag'), ('barricade'), ('hedgehog'), ('rock'), ('bunker'), ('tower'), ('flag'), ('banner'), ('road'),
    ('medkit'), ('pistol'), ('rifle'), ('shotgun'), ('smg'), ('sniper'), ('launcher'), ('grenade'), ('explosive')
) as t (code)
where p.code = 'kenney-tiny'
on conflict (pack_id, code) do nothing;

insert into enemy_types (code, name, health, speed, damage, behavior, texture_code) values
    ('soldier',   'Fusilero',   3,  70, 1, 'patrol', 'soldier'),
    ('grenadier', 'Granadero',  3,  62, 1, 'patrol', 'grenadier'),
    ('tank',      'Tanque',     25, 40, 2, 'chase',  'tank'),
    ('artillery', 'Artillería', 6,  0,  1, 'idle',   'artillery'),
    ('legionary', 'Legionario', 4,  88, 1, 'chase',  'legionary'),
    ('captain',   'Capitán',    9,  52, 2, 'chase',  'captain')
on conflict (code) do nothing;

insert into character_lines (kind, line) values
    ('ally',  '¡Cúbrete detrás de los sacos terreros!'),
    ('ally',  'Dispara a los barriles rojos: explotan y arrasan con todo.'),
    ('ally',  'La artillería no se mueve. Acércate rodando con Shift.'),
    ('ally',  'Los cofres esconden pistolas, fusiles y botiquines.'),
    ('guard', 'Nadie cruza este puente sin permiso.'),
    ('guard', 'El tanque enemigo aguanta mucho: usa el lanzacohetes.'),
    ('guard', 'Si oyes un silbido, aléjate: es una granada.')
on conflict (kind, line) do nothing;

"""


def read_grid(path: Path) -> list:
    rows = [line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
    assert len(rows) == ROWS, f"{path.name}: {len(rows)} rows, expected {ROWS}"
    for n, row in enumerate(rows):
        assert len(row) == COLUMNS, f"{path.name}: row {n} has {len(row)} columns"
        unknown = set(row) - set(KINDS) - {"."}
        assert not unknown, f"{path.name}: unknown characters {unknown}"
    return rows


def on_road(rows: list, col: int, row: int):
    """The ground kind most of the neighbours have, when at least two are road; else None."""
    around = ((col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1))
    roads = [rows[r][c] for c, r in around if 0 <= c < COLUMNS and 0 <= r < ROWS and rows[r][c] in GROUNDS]
    if len(roads) < 2:
        return None
    return GROUNDS[max(set(roads), key=roads.count)]


def scene_of(rows: list) -> list:
    objects, counts = [], {}

    def add(kind: str, col: int, row: int) -> None:
        counts[kind] = counts.get(kind, 0) + 1
        objects.append({"id": f"{kind}-{counts[kind]}", "kind": kind,
                        "x": col * TILE + TILE // 2, "y": row * TILE + TILE // 2})

    for row, line in enumerate(rows):
        for col, char in enumerate(line):
            if char == ".":
                continue
            kind = KINDS[char]
            ground = on_road(rows, col, row) if kind in ON_ROAD else None
            if ground:
                add(ground, col, row)
            add(kind, col, row)
    return objects


def check(code: str, rows: list) -> None:
    starts = [(c, r) for r, line in enumerate(rows) for c, ch in enumerate(line) if ch == "P"]
    assert len(starts) == 1, f"{code}: needs exactly one player"
    seen, queue = {starts[0]}, deque(starts)
    while queue:
        col, row = queue.popleft()
        for c, r in ((col + 1, row), (col - 1, row), (col, row + 1), (col, row - 1)):
            if 0 <= c < COLUMNS and 0 <= r < ROWS and (c, r) not in seen and KINDS.get(rows[r][c]) not in SOLID:
                seen.add((c, r))
                queue.append((c, r))
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch == "C":
                assert (c, r) in seen, f"{code}: the chest at ({c}, {r}) cannot be reached"


def sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> None:
    values = []
    for code, grid_name, name, description in MAPS:
        rows = read_grid(ROOT / "maps" / grid_name)
        check(code, rows)
        scene = scene_of(rows)
        assert len(scene) <= MAX_OBJECTS, f"{code}: {len(scene)} objects, at most {MAX_OBJECTS}"
        print(f"{code:15} {len(scene):4} objects")
        values.append(f"    ({sql_text(code)}, {sql_text(name)}, {sql_text(description)},\n"
                      f"     {sql_text(json.dumps(scene, separators=(',', ':')))}::jsonb)")
    sql = ("-- Ready-made maps: Kenney's sample maps (CC0) and our battle maps, see maps/README.md.\n"
           "-- Generated by tools/build_maps.py from maps/kenney/*.txt and maps/battle/*.txt; do not edit by hand.\n"
           + NEW_KINDS_SQL
           + "insert into level_templates (code, name, description, scene) values\n"
           + ",\n".join(values)
           + "\non conflict (code) do update\n"
           + "    set name = excluded.name, description = excluded.description, scene = excluded.scene;\n")
    out = ROOT / "migrations" / MIGRATION
    out.write_text(sql, encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
