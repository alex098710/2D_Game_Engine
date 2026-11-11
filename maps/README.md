# Ready-made maps

The maps offered when a project is created ("Nuevo proyecto") come from the sample maps that
[Kenney](https://kenney.nl) ships with his asset packs. They are public domain (CC0, see
`kenney/License.txt`): no permission or credit is needed, but we credit Kenney anyway.

| Map | Code | Source |
|---|---|---|
| Mazmorra (Kenney) | `kenney-dungeon` | [Tiny Dungeon](https://kenney.nl/assets/tiny-dungeon) 1.0, `Tiled/sampleMap.tmx` (32 x 20) |
| Reino (Kenney) | `kenney-kingdom` | [1-Bit Pack](https://kenney.nl/assets/1-bit-pack) 1.2, `Tilemap/sample_fantasy.tmx` (48 x 24) |
| Casa (Kenney) | `kenney-house` | [1-Bit Pack](https://kenney.nl/assets/1-bit-pack) 1.2, `Tilemap/sample_interior.tmx` (48 x 24) |
| Ciudad (Kenney) | `kenney-city` | [1-Bit Pack](https://kenney.nl/assets/1-bit-pack) 1.2, `Tilemap/sample_urban.tmx` (48 x 24) |
| Aldea (Kenney) | `kenney-village` | [Roguelike/RPG pack](https://kenney.nl/assets/roguelike-rpg-pack), `Map/sample_map.tmx` (columns 11-60, rows 13-42 of 100 x 100) |

The packs were downloaded from kenney.nl on 2026-10-27 (the Roguelike/RPG pack and the urban
sample on 2026-10-28). Tiny Dungeon is the same pack the game's
textures already come from.

## Battle maps (our own)

| Map | Code | Source |
|---|---|---|
| Frente de batalla | `battle-front` | drawn by `tools/draw_battle_maps.py` (`battle/front.txt`) |
| Asedio al búnker | `battle-siege` | drawn by `tools/draw_battle_maps.py` (`battle/siege.txt`) |

They are not converted from a source map: the script paints them with simple shapes (roads, a river,
sandbag lines, bases). Run it and then `python tools/build_maps.py`. Their extra characters:

| Char | Kind | Char | Kind | Char | Kind |
|---|---|---|---|---|---|
| `S` | `soldier` | `G` | `grenadier` | `K` | `tank` |
| `A` | `artillery` | `L` | `legionary` | `Q` | `captain` |
| `y` | `ally` | `u` | `guard` | `~` | `sandbag` |
| `\|` | `barricade` | `x` | `hedgehog` | `H` | `bunker` |
| `W` | `tower` | `F` | `flag` | `!` | `banner` |
| `o` | `rock` | `-` | `road` | `+` | `medkit` |
| `X` | `explosive` | `1`-`7` | `pistol`, `rifle`, `shotgun`, `smg`, `sniper`, `launcher`, `grenade` | | |

A person or an item standing among road tiles (`-`) gets a `road` under it, like `path` for `=`.

## How a Tiled map becomes a scene

The engine's world is 50 x 30 tiles of 32 px, and every Kenney tile (16 px, drawn at 2x) becomes
one tile of the world. Each `kenney/*.txt` file is that 50 x 30 grid, one character per tile:

| Char | Kind | Char | Kind | Char | Kind |
|---|---|---|---|---|---|
| `.` | nothing | `#` | `wall` | `T` | `tree` |
| `b` | `bush` | `f` | `fence` | `B` | `box` |
| `R` | `barrel` | `^` | `spike` | `C` | `chest` |
| `v` | `villager` | `k` | `knight` | `z` | `wizard` |
| `e` | `enemy` | `a` | `bat` | `s` | `spider` |
| `O` | `brute` | `P` | `player` | `g` | `ghost` |
| `c` | `coin` | `p` | `potion` | `=` | `path` |
| `d` | `dagger` | `h` | `hammer` | `l` | `spear` |
| `t` | `staff` | `w` | `water` | `_` | `bridge` |
| `:` | `sand` | `m` | `marksman` | `n` | `necromancer` |
| `D` | `demon` | `M` | `mimic` | `r` | `rat` |

`path` is ground (a road, a sidewalk or stone) with no body. When a person, an enemy or an item
stands on a tile with road on two or more sides, the builder puts a `path` under it too.

Tiles of the Kenney sheets (index = Tiled gid - 1 for Tiny Dungeon, gid for the 1-Bit Pack and the
Roguelike/RPG pack):

- **Tiny Dungeon** - walls: 1-8, 13-20, 25-29, 31, 32, 36-40, 43, 44, 57-59; floor, dirt, doors and
  rails: nothing; cabinets, tables, stools and mine carts (54, 55, 63-66, 72-75): `box`; 82
  `barrel`; 89 `chest`; 77 `fence`; 120 `bat`; 122 `spider`; 109 `brute`; 123, 124 `enemy`; people:
  84, 111 `wizard`, 87, 97 `knight`, 86, 98, 100 `villager`.
- **1-Bit Pack, fantasy** - castle, houses, roofs, statues and graves (354-360, 369, 385-387, 401,
  417, 422, 424, 449-451, 488, 491-493, 523-525, 556): `wall`; trees 33, 38, 68: `tree`; 71: `bush`;
  the moat and the river (137, 138): `water`, with a `bridge` where the moat opens; 102, 166: `fence`; 167 `chest`; 227, 241, 297, 452: `box`; 453 `barrel`;
  481 (bones) `spike`; grass, paths, crops, doors and signs: nothing.
- **1-Bit Pack, interior** - 417, 419: `wall`; furniture (228, 229, 236, 237, 239, 257, 258,
  260-262, 265, 269, 273, 305, 337): `box`; 35 `tree`; 59, 154 `villager`; 63 `knight`; 89
  `wizard`; 218 `enemy`; floor, door and candles: nothing.
- **1-Bit Pack, urban** - buildings, roofs, walls and windows (99, 326, 328, 331, 358, 360, 362,
  394, 422, 424, 427, 488, 529-531, 555, 556, 561, 563, 587, 593-595, 625-627, 657, 659, 689-691):
  `wall`; roads, lane marks, sidewalks and rails (14-17, 46-48, 73, 107, 161): `path`; trees 33, 35,
  68: `tree`; rock 70: `bush`; water 169-171: `water`; railings, hedges and lamp posts (130, 205, 397,
  428): `fence`; hydrants, mailboxes and bins (393, 398, 429, 430): `barrel`; cars, vans, trucks,
  buses, crates and benches (367, 401, 432, 462, 621, 622, 653, 654, 716, 719, 750, 751): `box`;
  grass, flowers and signs: nothing.
- **Roguelike/RPG pack** (all five layers; the strongest wins) - roofs, house walls, windows, tents,
  stalls and graves (11, 68, 330, 332, 565-567, 617, 618, 621, 622, 674, 675, 678-681, 869-875,
  1157-1160, 1218-1233, 1251, 1275-1290, 1332-1347, 1392, 1407): `wall`; water and rocks (3-5,
  58-62, 116-119, 174-176, 231-233, 288-290, 1424): `water`; rock 1423: `bush`; dirt and stone paths (405-409,
  463, 466, 519-523, 577-580, 635-637, 690, 808, 862, 864, 919-921, 977, 978, 1033): `path`; trees
  (527, 537, 541, 584, 587, 641, 644, 651, 655): `tree`; shrubs and stumps (539, 594, 598, 599,
  1137): `bush`; fences (736, 737, 850-852, 966, 1360, 1417, 1420): `fence`; barrels and pots (24,
  426): `barrel`; tables, beds and logs (127, 241, 297, 1080): `box`; campfire 471: `spike`; doors
  leave an opening; grass, flowers and signs: nothing.

The city, the village and the kingdom add people, enemies (archers, necromancers, rats, a mimic and,
in the village and the kingdom, a demon boss), coins, chests, potions and weapons on open tiles so
they can be played as they are. The other samples have no player, so each grid adds a `P` on an
open tile. The house is scenery: add coins or enemies in the editor (or with the AI) to give it a
goal.

Migrations never change once applied: 088 and 089 seeded the first maps, and the newest one
(`MIGRATION` in the builder, now 090) re-seeds every map with `on conflict do update`. To change a
map, edit its grid, give `MIGRATION` a new number and rebuild:

```
python tools/build_maps.py     # checks every map and writes the newest map migration
```
