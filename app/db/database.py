import sqlite3
from pathlib import Path

from app.db.schema import SCHEMA_SQL


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._migrate_legacy_schema(conn)
            conn.commit()

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "inbound_catalog" in tables:
            catalog_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(inbound_catalog)").fetchall()
            }
            if "panel_inbound_id" not in catalog_columns:
                conn.execute(
                    "ALTER TABLE inbound_catalog ADD COLUMN panel_inbound_id INTEGER"
                )
            if "endpoint_index" not in catalog_columns:
                conn.execute(
                    "ALTER TABLE inbound_catalog ADD COLUMN endpoint_index INTEGER NOT NULL DEFAULT 0"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_catalog_panel_id ON inbound_catalog(panel_inbound_id)"
            )

        if "client_index" not in tables:
            conn.execute(
                """
                CREATE TABLE client_index (
                    sub_id TEXT PRIMARY KEY,
                    group_name TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    enable INTEGER NOT NULL DEFAULT 1,
                    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_client_group ON client_index(group_name)"
            )

        if "group_balancers" not in tables:
            conn.execute(
                """
                CREATE TABLE group_balancers (
                    group_name TEXT PRIMARY KEY,
                    balancer_tag TEXT NOT NULL REFERENCES balancers(tag) ON DELETE CASCADE
                )
                """
            )

        if "balancers" in tables:
            balancer_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(balancers)").fetchall()
            }
            if "scope" not in balancer_columns:
                conn.execute(
                    "ALTER TABLE balancers ADD COLUMN scope TEXT NOT NULL DEFAULT 'disabled'"
                )
            if "scope_target" not in balancer_columns:
                conn.execute(
                    "ALTER TABLE balancers ADD COLUMN scope_target TEXT NOT NULL DEFAULT ''"
                )

            if "group_balancers" in tables:
                rows = conn.execute(
                    "SELECT group_name, balancer_tag FROM group_balancers"
                ).fetchall()
                for row in rows:
                    conn.execute(
                        """
                        UPDATE balancers
                        SET scope = 'group', scope_target = ?
                        WHERE tag = ? AND scope = 'disabled' AND scope_target = ''
                        """,
                        (str(row["group_name"]), str(row["balancer_tag"])),
                    )

        if "balancers" not in tables:
            return

        columns = [
            row[1] for row in conn.execute("PRAGMA table_info(balancers)").fetchall()
        ]
        if "sub_id" not in columns:
            return

        old_balancers = conn.execute(
            "SELECT id, sub_id, tag, remarks, strategy FROM balancers"
        ).fetchall()
        old_members = conn.execute(
            "SELECT balancer_id, inbound_fingerprint FROM balancer_members"
        ).fetchall()
        old_id_to_tag = {int(row["id"]): str(row["tag"]) for row in old_balancers}

        conn.execute("DROP TABLE balancer_members")
        conn.execute("DROP TABLE balancers")
        conn.execute("DROP TABLE IF EXISTS subscription_profiles")
        conn.executescript(
            """
            CREATE TABLE balancers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT NOT NULL UNIQUE,
                remarks TEXT NOT NULL DEFAULT '',
                strategy TEXT NOT NULL DEFAULT 'roundRobin'
            );
            CREATE TABLE balancer_members (
                balancer_id INTEGER NOT NULL REFERENCES balancers(id) ON DELETE CASCADE,
                inbound_fingerprint TEXT NOT NULL,
                PRIMARY KEY (balancer_id, inbound_fingerprint)
            );
            """
        )

        tag_to_new_id: dict[str, int] = {}
        for row in old_balancers:
            tag = str(row["tag"])
            if tag in tag_to_new_id:
                continue
            cursor = conn.execute(
                """
                INSERT INTO balancers (tag, remarks, strategy)
                VALUES (?, ?, ?)
                """,
                (tag, str(row["remarks"]), str(row["strategy"])),
            )
            tag_to_new_id[tag] = int(cursor.lastrowid)

        for member in old_members:
            tag = old_id_to_tag.get(int(member["balancer_id"]))
            if tag is None:
                continue
            new_id = tag_to_new_id.get(tag)
            if new_id is None:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO balancer_members (balancer_id, inbound_fingerprint)
                VALUES (?, ?)
                """,
                (new_id, str(member["inbound_fingerprint"])),
            )