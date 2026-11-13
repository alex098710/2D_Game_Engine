from psycopg.types.json import Jsonb

from .project import Project

_COLUMNS = "id, owner_id, name, scene, updated_at"
MAX_VERSIONS_LISTED = 50


class ProjectRepository:
    """Reads and writes the 'projects' table (and its versions) with hand-written SQL.

    Every query that touches an existing project filters by owner_id, so a
    user can never read or change another user's project: if the project
    does not exist or belongs to someone else, the result is None.
    """

    def __init__(self, connection):
        self._connection = connection

    def create(self, owner_id: int, name: str, scene: list) -> Project:
        row = self._connection.execute(
            f"insert into projects (owner_id, name, scene) values (%s, %s, %s) returning {_COLUMNS}",
            (owner_id, name, Jsonb(scene)),
        ).fetchone()
        return Project(**row)

    def list_by_owner(self, owner_id: int) -> list:
        rows = self._connection.execute(
            f"select {_COLUMNS} from projects where owner_id = %s order by updated_at desc",
            (owner_id,),
        ).fetchall()
        return [Project(**row) for row in rows]

    def find_by_id(self, project_id: int, owner_id: int):
        row = self._connection.execute(
            f"select {_COLUMNS} from projects where id = %s and owner_id = %s",
            (project_id, owner_id),
        ).fetchone()
        return Project(**row) if row else None

    def update_scene(self, project_id: int, owner_id: int, scene: list):
        row = self._connection.execute(
            f"update projects set scene = %s, updated_at = now() "
            f"where id = %s and owner_id = %s returning {_COLUMNS}",
            (Jsonb(scene), project_id, owner_id),
        ).fetchone()
        return Project(**row) if row else None

    def rename(self, project_id: int, owner_id: int, name: str):
        row = self._connection.execute(
            f"update projects set name = %s, updated_at = now() "
            f"where id = %s and owner_id = %s returning {_COLUMNS}",
            (name, project_id, owner_id),
        ).fetchone()
        return Project(**row) if row else None

    def delete(self, project_id: int, owner_id: int) -> bool:
        cursor = self._connection.execute(
            "delete from projects where id = %s and owner_id = %s", (project_id, owner_id)
        )
        return cursor.rowcount == 1

    def save_version(self, project_id: int, owner_id: int, scene: list, note: str = "") -> int:
        """Store a snapshot of the scene and return its version number (1, 2, 3...)."""
        row = self._connection.execute(
            "insert into project_versions (project_id, version_number, scene, note, created_by) "
            "select %s, coalesce(max(version_number), 0) + 1, %s, %s, %s "
            "from project_versions where project_id = %s "
            "returning version_number",
            (project_id, Jsonb(scene), note, owner_id, project_id),
        ).fetchone()
        return row["version_number"]

    def list_versions(self, project_id: int) -> list:
        return self._connection.execute(
            "select version_number, note, created_at, jsonb_array_length(scene) as object_count "
            "from project_versions where project_id = %s order by version_number desc limit %s",
            (project_id, MAX_VERSIONS_LISTED),
        ).fetchall()

    def find_version(self, project_id: int, version_number: int):
        row = self._connection.execute(
            "select scene from project_versions where project_id = %s and version_number = %s",
            (project_id, version_number),
        ).fetchone()
        return row["scene"] if row else None

    def creation_kinds(self, owner_id: int, ids: list) -> dict:
        """{creation id: base kind} of this owner's enemy and object creations among ids."""
        rows = self._connection.execute(
            "select id, base_kind from custom_entities "
            "where owner_id = %s and id = any(%s) and category in ('enemy', 'object')",
            (owner_id, ids),
        ).fetchall()
        return {row["id"]: row["base_kind"] for row in rows}

    def commit(self) -> None:
        """Save what the request wrote so far and end the transaction.

        Called before a slow call to the AI service, so the database
        connection is not held while it answers.
        """
        self._connection.commit()

    def template_scene(self, code: str):
        row = self._connection.execute(
            "select scene from level_templates where code = %s", (code,)
        ).fetchone()
        return row["scene"] if row else None

    def list_templates(self) -> list:
        return self._connection.execute(
            "select code, name, description, jsonb_array_length(scene) as object_count, scene "
            "from level_templates order by id"
        ).fetchall()
