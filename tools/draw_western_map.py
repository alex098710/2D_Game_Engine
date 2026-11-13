"""Draw the ready-made map "Duelo en el pueblo" and write its migration.

    python tools/draw_western_map.py

A Western town on a 1600 x 960 world: a dirt main street from west to east, the
saloon with its boardwalk on the north side, cabins on both sides, a wagon,
hay, crates and troughs as covers, lamps along the street and cacti outside
the town. The hero starts at the west entrance; five bandits hold the east end.

Objects are placed by their centre (like the rest of the engine). Before
writing, the script checks that every object is fully inside the world, that
no two solid objects overlap and that there is exactly one player.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "migrations" / "095_western_town.sql"
WIDTH, HEIGHT, TILE = 1600, 960, 32

SIZES = {
    "saloon": (160, 128), "cabin": (96, 96), "wagon": (64, 48), "hay": (32, 32), "crates": (64, 48),
    "trough": (64, 32), "cactus": (32, 48), "lamp": (32, 64), "boardwalk": (32, 32), "dirt": (32, 32),
    "bandit": (24, 28), "player": (24, 24), "coin": (16, 16), "villager": (24, 28), "chest": (28, 24),
    "pistol": (22, 16), "medkit": (22, 20), "barrel": (28, 30), "fence": (32, 32), "tree": (32, 32),
    "explosive": (28, 30),
}
GROUND = {"dirt", "boardwalk"}
NOT_SOLID = GROUND | {"coin", "pistol", "medkit", "player", "bandit", "villager"}

objects: list = []


def put(kind: str, x: float, y: float) -> None:
    objects.append({"id": f"{kind}-{sum(1 for o in objects if o['kind'] == kind) + 1}", "kind": kind, "x": x, "y": y})


def tiles(kind: str, col0: int, row0: int, cols: int, rows: int) -> None:
    for row in range(row0, row0 + rows):
        for col in range(col0, col0 + cols):
            put(kind, col * TILE + TILE / 2, row * TILE + TILE / 2)


# --- ground: the main street (rows 13-19) and a cross street by the saloon ---------------
tiles("dirt", 0, 13, 50, 7)
tiles("dirt", 22, 20, 6, 10)
# Boardwalks in front of the saloon and the cabins of the north side.
tiles("boardwalk", 20, 12, 10, 1)
tiles("boardwalk", 5, 12, 6, 1)
tiles("boardwalk", 39, 12, 6, 1)

# --- buildings -------------------------------------------------------------------------
put("saloon", 800, 320)          # north side, centre (x 720-880, y 256-384)
put("cabin", 256, 336)           # north-west (x 208-304, y 288-384)
put("cabin", 1344, 336)          # north-east
put("cabin", 448, 752)           # south-west, across the street
put("cabin", 1120, 752)          # south-east

# --- covers along the street (the duel) ---------------------------------------------------
put("wagon", 560, 528)
put("hay", 512, 576)
put("hay", 608, 592)
put("crates", 1040, 528)
put("hay", 992, 592)
put("trough", 640, 432)
put("trough", 960, 432)
put("crates", 1248, 592)
put("explosive", 1312, 480)
put("barrel", 704, 640)
put("barrel", 896, 640)

# --- street lamps and cacti ----------------------------------------------------------------
for x in (176, 432, 1168, 1424):
    put("lamp", x, 352)
for x in (96, 1504):
    put("lamp", x, 688)
for x, y in ((64, 96), (176, 160), (1536, 112), (1440, 192), (96, 880), (1520, 880), (288, 912), (1312, 912)):
    put("cactus", x, y)
for x in range(640, 960, 32):    # a fence behind the saloon
    put("fence", x, 208)

# --- people, loot and the bandits -----------------------------------------------------------
put("player", 80, 512)
put("villager", 760, 400)
put("villager", 840, 400)
put("pistol", 176, 544)
put("medkit", 800, 720)
put("chest", 1344, 416)
for x in range(240, 1400, 160):
    put("coin", x, 480 if (x // 160) % 2 else 560)
for x, y in ((1136, 496), (1184, 624), (1376, 544), (1488, 464), (1504, 624)):
    put("bandit", x, y)


def box(obj: dict) -> tuple:
    w, h = SIZES[obj["kind"]]
    return obj["x"] - w / 2, obj["y"] - h / 2, obj["x"] + w / 2, obj["y"] + h / 2


def check() -> None:
    assert sum(o["kind"] == "player" for o in objects) == 1, "exactly one player"
    for obj in objects:
        left, top, right, bottom = box(obj)
        assert left >= 0 and top >= 0 and right <= WIDTH and bottom <= HEIGHT, f"{obj['id']} leaves the world"
    solids = [o for o in objects if o["kind"] not in NOT_SOLID]
    for i, a in enumerate(solids):
        ax0, ay0, ax1, ay1 = box(a)
        for b in solids[i + 1:]:
            bx0, by0, bx1, by1 = box(b)
            assert ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0, f"{a['id']} overlaps {b['id']}"
    # People and pick-ups stand clear of solids.
    for obj in objects:
        if obj["kind"] in NOT_SOLID - GROUND:
            ox0, oy0, ox1, oy1 = box(obj)
            for s in solids:
                sx0, sy0, sx1, sy1 = box(s)
                assert ox1 <= sx0 or sx1 <= ox0 or oy1 <= sy0 or sy1 <= oy0, f"{obj['id']} is inside {s['id']}"


def main() -> None:
    check()
    scene = json.dumps(objects, separators=(",", ":"), ensure_ascii=False)
    kinds = """-- The Western town: buildings, covers, ground and the bandit (generated by
-- tools/draw_western_map.py together with the map "Duelo en el pueblo").
insert into object_kinds (code, name, category, solid, movable, collectible, hostile) values
    ('saloon',    'Saloon',             'building',    true,  false, false, false),
    ('cabin',     'Cabaña',             'building',    true,  false, false, false),
    ('wagon',     'Carreta con heno',   'obstacle',    true,  false, false, false),
    ('hay',       'Fardo de heno',      'obstacle',    true,  false, false, false),
    ('crates',    'Pila de cajas',      'obstacle',    true,  false, false, false),
    ('trough',    'Abrevadero',         'obstacle',    true,  false, false, false),
    ('cactus',    'Cactus',             'obstacle',    true,  false, false, false),
    ('lamp',      'Farol',              'decoration',  true,  false, false, false),
    ('boardwalk', 'Pasarela de tablas', 'decoration',  false, false, false, false),
    ('dirt',      'Tierra',             'decoration',  false, false, false, false),
    ('bandit',    'Bandido',            'enemy',       true,  true,  false, true)
on conflict (code) do nothing;

insert into object_physics (kind, body_type, material_id, mass, drag, immovable)
select k.kind, k.body_type, m.id, k.mass, k.drag, k.immovable
from (values
    ('saloon',    'static',  'wood',  1.0, 0,   true),
    ('cabin',     'static',  'wood',  1.0, 0,   true),
    ('wagon',     'static',  'wood',  1.0, 0,   true),
    ('hay',       'static',  'wood',  1.0, 0,   true),
    ('crates',    'static',  'wood',  1.0, 0,   true),
    ('trough',    'static',  'wood',  1.0, 0,   true),
    ('cactus',    'static',  'wood',  1.0, 0,   true),
    ('lamp',      'static',  'stone', 1.0, 0,   true),
    ('boardwalk', 'none',    'wood',  1.0, 0,   true),
    ('dirt',      'none',    'stone', 1.0, 0,   true),
    ('bandit',    'dynamic', 'flesh', 1.5, 200, false)
) as k (kind, body_type, material, mass, drag, immovable)
join physics_materials m on m.code = k.material
on conflict (kind) do nothing;

insert into textures (pack_id, code, kind, file_path, width, height, frames)
select p.id, t.code, t.code, 'textures/' || t.code || '.png', t.w, t.h, 1
from texture_packs p
cross join (values
    ('saloon', 160, 128), ('cabin', 96, 96), ('wagon', 64, 48), ('hay', 32, 32), ('crates', 64, 48),
    ('trough', 64, 32), ('cactus', 32, 48), ('lamp', 32, 64), ('boardwalk', 32, 32), ('dirt', 32, 32),
    ('bandit', 32, 32)
) as t (code, w, h)
where p.code = 'kenney-tiny'
on conflict (pack_id, code) do nothing;

insert into enemy_types (code, name, health, speed, damage, behavior, texture_code) values
    ('bandit', 'Bandido', 3, 82, 1, 'patrol', 'bandit')
on conflict (code) do nothing;

"""
    template = (
        "insert into level_templates (code, name, description, scene) values\n"
        "    ('western-duel', 'Duelo en el pueblo', "
        "'Un pueblo del oeste con saloon, cabañas y carretas: entras por el oeste y cinco bandidos "
        "te esperan al otro lado de la calle principal; cúbrete tras el heno y las cajas', "
        f"'{scene.replace(chr(39), chr(39) * 2)}')\n"
        "on conflict (code) do update set name = excluded.name, description = excluded.description, "
        "scene = excluded.scene;\n"
    )
    MIGRATION.write_text(kinds + template, encoding="utf-8")
    print(f"wrote {MIGRATION.name}: {len(objects)} objects")


if __name__ == "__main__":
    main()
