"""Draw the two battle maps as 50 x 30 grids in maps/battle/.

    python tools/draw_battle_maps.py     # then: python tools/build_maps.py

The battle maps are our own (no source map): they are painted here with simple
shapes (roads, rivers, sandbag lines, bases) so they are easy to tweak. The
characters are the ones of tools/build_maps.py (see maps/README.md).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLUMNS, ROWS = 50, 30


class Grid:
    def __init__(self) -> None:
        self.cells = [["."] * COLUMNS for _ in range(ROWS)]

    def put(self, col: int, row: int, char: str) -> None:
        if 0 <= col < COLUMNS and 0 <= row < ROWS:
            self.cells[row][col] = char

    def hline(self, row: int, c0: int, c1: int, char: str) -> None:
        for c in range(c0, c1 + 1):
            self.put(c, row, char)

    def vline(self, col: int, r0: int, r1: int, char: str) -> None:
        for r in range(r0, r1 + 1):
            self.put(col, r, char)

    def rect(self, c0: int, r0: int, c1: int, r1: int, char: str) -> None:
        for r in range(r0, r1 + 1):
            self.hline(r, c0, c1, char)

    def frame(self, c0: int, r0: int, c1: int, r1: int, char: str, gaps: tuple = ()) -> None:
        self.hline(r0, c0, c1, char)
        self.hline(r1, c0, c1, char)
        self.vline(c0, r0, r1, char)
        self.vline(c1, r0, r1, char)
        for col, row in gaps:
            self.put(col, row, "-")

    def scatter(self, points: list, char: str) -> None:
        for col, row in points:
            self.put(col, row, char)

    def text(self, header: str) -> str:
        return header + "\n".join("".join(row) for row in self.cells) + "\n"


def front_line() -> str:
    """Two camps split by a river: the blue base on the west, the red army on the east."""
    g = Grid()
    # Forest along the edges.
    g.scatter([(c, 0) for c in range(0, 50, 2)] + [(c, 29) for c in range(1, 50, 2)], "T")
    g.scatter([(0, r) for r in range(2, 28, 3)] + [(49, r) for r in range(1, 28, 3)], "T")
    # The river runs north to south with two bridges.
    for r in range(1, 29):
        g.put(24, r, "w")
        g.put(25, r, "w")
    for r in (8, 21):
        g.put(24, r, "_")
        g.put(25, r, "_")
    # Roads: a main road east-west through each bridge, a north-south road in each camp.
    g.hline(8, 2, 47, "-")
    g.hline(21, 2, 47, "-")
    g.vline(8, 3, 26, "-")
    g.vline(41, 3, 26, "-")
    for r in (8, 21):
        g.put(24, r, "_")
        g.put(25, r, "_")
    # Blue base (west): sandbag line with openings on the roads, bunker, tower, flags.
    g.vline(15, 3, 26, "~")
    g.put(15, 8, "-")
    g.put(15, 21, "-")
    g.scatter([(4, 4), (12, 4)], "F")
    g.scatter([(5, 12), (11, 17)], "H")
    g.put(4, 25, "W")
    g.scatter([(6, 10), (10, 19)], "y")
    g.scatter([(12, 13), (13, 23)], "u")
    g.put(4, 14, "P")
    g.scatter([(10, 12), (3, 22)], "+")
    g.put(12, 16, "C")
    g.scatter([(5, 6), (11, 25)], "1")
    g.put(13, 10, "2")
    # No man's land: hedgehogs, craters (hills), crates and kegs between the camps.
    g.scatter([(18, 4), (20, 11), (19, 17), (21, 26), (28, 5), (29, 14), (27, 24)], "x")
    g.scatter([(18, 14), (30, 18), (21, 3)], "o")
    g.scatter([(19, 9), (29, 10), (20, 20), (30, 22)], "X")
    g.scatter([(18, 24), (28, 2)], "B")
    g.scatter([(17, 6), (22, 13), (17, 19), (27, 9), (30, 26), (21, 16), (28, 16)], "c")
    g.put(22, 18, "C")
    # Red base (east): sandbags with gaps, artillery behind them, the tank by the command post.
    g.vline(34, 3, 26, "~")
    g.put(34, 8, "-")
    g.put(34, 21, "-")
    g.scatter([(45, 4), (37, 4)], "!")
    g.scatter([(44, 13), (38, 18)], "H")
    g.put(46, 25, "W")
    g.scatter([(33, 5), (33, 12), (33, 17), (33, 25)], "X")
    g.scatter([(37, 11), (38, 24)], "A")
    g.scatter([(36, 6), (36, 15), (39, 20), (37, 27)], "S")
    g.scatter([(39, 10), (43, 22)], "G")
    g.scatter([(31, 7), (31, 20), (36, 23)], "L")
    g.put(44, 16, "Q")
    g.put(45, 9, "K")
    g.scatter([(46, 18), (43, 6), (47, 13), (40, 27)], "c")
    g.put(47, 11, "C")
    g.put(39, 15, "6")
    g.put(42, 26, "7")
    return g.text(
        "# PixelForge battle map: Frente de batalla (drawn by tools/draw_battle_maps.py).\n"
        "# The blue base is on the west, the red army on the east, a river with two bridges between them.\n"
    )


def siege() -> str:
    """A red fortress of sandbags in the middle; the hero comes from the south."""
    g = Grid()
    g.scatter([(c, r) for r in range(0, 30) for c in range(0, 50) if (c < 3 or c > 46 or r < 2) and (c * 7 + r * 3) % 4 == 0], "T")
    # Roads to the fortress gates.
    g.vline(24, 2, 28, "-")
    g.hline(15, 3, 46, "-")
    # Outer wall of sandbags with four gates, towers in the corners.
    g.frame(12, 5, 37, 25, "~", gaps=((24, 5), (24, 25), (12, 15), (37, 15)))
    g.scatter([(12, 5), (37, 5), (12, 25), (37, 25)], "W")
    # Kegs against the wall: blow a hole where you like.
    g.scatter([(13, 9), (36, 9), (13, 21), (36, 21), (20, 6), (29, 24)], "X")
    # Inner keep: bunkers, flags, the command post and the tank.
    g.frame(19, 10, 30, 20, "|", gaps=((24, 10), (24, 20)))
    g.scatter([(21, 12), (28, 12), (21, 18), (28, 18)], "H")
    g.scatter([(23, 13), (26, 13)], "!")
    g.put(24, 14, "K")
    g.put(26, 17, "C")
    g.put(22, 16, "6")
    # Defenders.
    g.scatter([(16, 8), (33, 8), (16, 22), (33, 22)], "A")
    g.scatter([(15, 12), (34, 12), (18, 23), (31, 7), (24, 8)], "S")
    g.scatter([(15, 18), (34, 18), (24, 22)], "G")
    g.scatter([(20, 7), (29, 7), (17, 15), (32, 15), (27, 23)], "L")
    g.scatter([(14, 14), (35, 16)], "Q")
    g.scatter([(14, 7), (35, 7), (14, 23), (35, 23), (22, 11), (27, 19), (18, 13), (31, 17)], "c")
    # Outside: the hero's camp in the south, cover in the fields.
    g.put(24, 27, "P")
    g.scatter([(20, 27), (28, 27)], "y")
    g.put(22, 28, "+")
    g.put(26, 28, "C")
    g.put(21, 26, "4")
    g.put(27, 26, "3")
    g.scatter([(6, 6), (8, 12), (5, 20), (42, 6), (44, 13), (41, 22), (9, 26), (40, 27)], "x")
    g.scatter([(7, 9), (43, 9), (6, 24), (44, 24)], "o")
    g.scatter([(10, 18), (39, 11), (8, 3), (41, 3)], "~")
    g.scatter([(5, 4), (45, 4), (5, 27), (45, 27), (10, 10), (39, 19)], "c")
    g.put(44, 19, "C")
    g.put(5, 15, "5")
    g.put(7, 15, "+")
    return g.text(
        "# PixelForge battle map: Asedio al búnker (drawn by tools/draw_battle_maps.py).\n"
        "# A red fortress of sandbags in the middle; blow up the kegs to open a breach.\n"
    )


def main() -> None:
    out = ROOT / "maps" / "battle"
    out.mkdir(parents=True, exist_ok=True)
    (out / "front.txt").write_text(front_line(), encoding="utf-8")
    (out / "siege.txt").write_text(siege(), encoding="utf-8")
    print("wrote maps/battle/front.txt and maps/battle/siege.txt")


if __name__ == "__main__":
    main()
