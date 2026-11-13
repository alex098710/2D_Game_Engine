from psycopg.types.json import Jsonb

_CREATION_COLUMNS = "id, category, base_kind, name, tint, health, damage, speed, value, sprite_id, created_at, updated_at"
_EDITABLE = ("category", "base_kind", "name", "tint", "health", "damage", "speed", "value", "sprite_id")
_SPRITE_COLUMNS = "id, name, width, height, png, created_at"


class AdminRepository:
    """The admin panel of each account: 'user_balance' and 'custom_entities'.

    Every query filters by the owner, so one account never reads or changes
    another account's numbers or creations.
    """

    def __init__(self, connection):
        self._connection = connection

    # --- balance ---------------------------------------------------------------

    def balance(self, user_id: int) -> dict:
        row = self._connection.execute(
            "select heroes, enemies from user_balance where user_id = %s", (user_id,)
        ).fetchone()
        return {"heroes": dict(row["heroes"]), "enemies": dict(row["enemies"])} if row else {"heroes": {}, "enemies": {}}

    def save_balance(self, user_id: int, heroes: dict, enemies: dict) -> dict:
        row = self._connection.execute(
            "insert into user_balance (user_id, heroes, enemies) values (%s, %s, %s) "
            "on conflict (user_id) do update set heroes = excluded.heroes, enemies = excluded.enemies, "
            "updated_at = now() returning heroes, enemies",
            (user_id, Jsonb(heroes), Jsonb(enemies)),
        ).fetchone()
        return {"heroes": dict(row["heroes"]), "enemies": dict(row["enemies"])}

    # --- creations -------------------------------------------------------------

    def creations(self, user_id: int) -> list:
        rows = self._connection.execute(
            f"select {_CREATION_COLUMNS} from custom_entities where owner_id = %s order by category, id",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def count(self, user_id: int) -> int:
        return self._connection.execute(
            "select count(*) as n from custom_entities where owner_id = %s", (user_id,)
        ).fetchone()["n"]

    def create(self, user_id: int, values: dict) -> dict:
        columns = ", ".join(_EDITABLE)
        row = self._connection.execute(
            f"insert into custom_entities (owner_id, {columns}) values (%s, {', '.join(['%s'] * len(_EDITABLE))}) "
            f"returning {_CREATION_COLUMNS}",
            (user_id, *(values.get(field) for field in _EDITABLE)),
        ).fetchone()
        return dict(row)

    def update(self, user_id: int, creation_id: int, values: dict):
        sets = ", ".join(f"{field} = %s" for field in _EDITABLE)
        row = self._connection.execute(
            f"update custom_entities set {sets}, updated_at = now() where id = %s and owner_id = %s "
            f"returning {_CREATION_COLUMNS}",
            (*(values.get(field) for field in _EDITABLE), creation_id, user_id),
        ).fetchone()
        return dict(row) if row else None

    def delete(self, user_id: int, creation_id: int) -> bool:
        row = self._connection.execute(
            "delete from custom_entities where id = %s and owner_id = %s returning id", (creation_id, user_id)
        ).fetchone()
        return row is not None

    # --- pictures (only the clean copies made by sprite_scan.py) ---------------

    def sprites(self, user_id: int) -> list:
        rows = self._connection.execute(
            f"select {_SPRITE_COLUMNS} from user_sprites where owner_id = %s order by id", (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def sprite_count(self, user_id: int) -> int:
        return self._connection.execute(
            "select count(*) as n from user_sprites where owner_id = %s", (user_id,)
        ).fetchone()["n"]

    def owns_sprite(self, user_id: int, sprite_id: int) -> bool:
        return self._connection.execute(
            "select 1 from user_sprites where id = %s and owner_id = %s", (sprite_id, user_id)
        ).fetchone() is not None

    def add_sprite(self, user_id: int, name: str, png: bytes, width: int, height: int, sha256: str) -> dict:
        """Store a clean picture; the same picture twice is kept once (and renamed)."""
        row = self._connection.execute(
            "insert into user_sprites (owner_id, name, png, width, height, sha256) values (%s, %s, %s, %s, %s, %s) "
            "on conflict (owner_id, sha256) do update set name = excluded.name "
            f"returning {_SPRITE_COLUMNS}",
            (user_id, name, png, width, height, sha256),
        ).fetchone()
        return dict(row)

    def delete_sprite(self, user_id: int, sprite_id: int) -> bool:
        row = self._connection.execute(
            "delete from user_sprites where id = %s and owner_id = %s returning id", (sprite_id, user_id)
        ).fetchone()
        return row is not None
