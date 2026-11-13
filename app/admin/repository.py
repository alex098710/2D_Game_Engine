from psycopg.types.json import Jsonb

_CREATION_COLUMNS = "id, category, base_kind, name, tint, health, damage, speed, value, created_at, updated_at"
_EDITABLE = ("category", "base_kind", "name", "tint", "health", "damage", "speed", "value")


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
            (user_id, *(values[field] for field in _EDITABLE)),
        ).fetchone()
        return dict(row)

    def update(self, user_id: int, creation_id: int, values: dict):
        sets = ", ".join(f"{field} = %s" for field in _EDITABLE)
        row = self._connection.execute(
            f"update custom_entities set {sets}, updated_at = now() where id = %s and owner_id = %s "
            f"returning {_CREATION_COLUMNS}",
            (*(values[field] for field in _EDITABLE), creation_id, user_id),
        ).fetchone()
        return dict(row) if row else None

    def delete(self, user_id: int, creation_id: int) -> bool:
        row = self._connection.execute(
            "delete from custom_entities where id = %s and owner_id = %s returning id", (creation_id, user_id)
        ).fetchone()
        return row is not None
