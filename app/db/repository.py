import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from app.db.database import Database
from app.models.balancer import BalancerScope, normalize_scope, normalize_strategy
from app.models.inbound import InboundDescriptor


@dataclass
class BalancerRecord:
    id: int
    tag: str
    remarks: str
    strategy: str
    scope: BalancerScope
    scope_target: str
    member_fingerprints: list[str]


@dataclass
class ClientRecord:
    sub_id: str
    group_name: str
    email: str
    enable: bool


@dataclass
class GroupAssignment:
    group_name: str
    balancer_tag: str
    client_count: int


class CatalogRepository:
    def __init__(self, database: Database) -> None:
        self._db = database
        database.initialize()

    def get_setting(self, key: str) -> str | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._db.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            conn.commit()

    def upsert_inbounds(self, inbounds: list[InboundDescriptor]) -> tuple[int, int]:
        now = datetime.now(timezone.utc).isoformat()
        seen: set[str] = set()
        upserted = 0

        with self._db.connect() as conn:
            for inbound in inbounds:
                seen.add(inbound.fingerprint)
                conn.execute(
                    """
                    INSERT INTO inbound_catalog (
                        fingerprint, remarks, protocol, network, address,
                        path, port, security, panel_inbound_id, endpoint_index,
                        is_active, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        remarks = excluded.remarks,
                        protocol = excluded.protocol,
                        network = excluded.network,
                        address = excluded.address,
                        path = excluded.path,
                        port = excluded.port,
                        security = excluded.security,
                        panel_inbound_id = excluded.panel_inbound_id,
                        endpoint_index = excluded.endpoint_index,
                        is_active = 1,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        inbound.fingerprint,
                        inbound.remarks,
                        inbound.protocol,
                        inbound.network,
                        inbound.address,
                        inbound.path,
                        inbound.port,
                        inbound.security,
                        inbound.panel_inbound_id,
                        inbound.endpoint_index,
                        now,
                    ),
                )
                upserted += 1

            if seen:
                placeholders = ",".join("?" for _ in seen)
                deactivated = conn.execute(
                    f"""
                    UPDATE inbound_catalog
                    SET is_active = 0
                    WHERE fingerprint NOT IN ({placeholders}) AND is_active = 1
                    """,
                    tuple(seen),
                ).rowcount
            else:
                deactivated = conn.execute(
                    "UPDATE inbound_catalog SET is_active = 0 WHERE is_active = 1"
                ).rowcount

            conn.commit()

        return upserted, deactivated

    def list_inbounds(self, *, active_only: bool = False) -> list[dict[str, object]]:
        query = "SELECT * FROM inbound_catalog"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY remarks, panel_inbound_id, endpoint_index, fingerprint"

        with self._db.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]

    def get_fingerprints_by_panel_ids(
        self,
        panel_ids: list[int],
        *,
        active_only: bool = True,
    ) -> list[str]:
        if not panel_ids:
            return []

        placeholders = ",".join("?" for _ in panel_ids)
        query = f"""
            SELECT fingerprint
            FROM inbound_catalog
            WHERE panel_inbound_id IN ({placeholders})
        """
        params: list[object] = list(panel_ids)
        if active_only:
            query += " AND is_active = 1"
        query += " ORDER BY panel_inbound_id, endpoint_index, fingerprint"

        with self._db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [str(row["fingerprint"]) for row in rows]

    def create_balancer(
        self,
        tag: str,
        remarks: str,
        strategy: str,
        member_fingerprints: list[str],
        *,
        scope: str = "disabled",
        scope_target: str = "",
    ) -> int:
        normalized_scope = normalize_scope(scope)
        normalized_strategy = normalize_strategy(strategy)
        target = scope_target.strip()

        with self._db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO balancers (tag, remarks, strategy, scope, scope_target)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tag) DO UPDATE SET
                    remarks = excluded.remarks,
                    strategy = excluded.strategy,
                    scope = excluded.scope,
                    scope_target = excluded.scope_target
                """,
                (tag, remarks, normalized_strategy, normalized_scope, target),
            )
            balancer_id = cursor.lastrowid
            if balancer_id == 0:
                row = conn.execute(
                    "SELECT id FROM balancers WHERE tag = ?",
                    (tag,),
                ).fetchone()
                balancer_id = int(row["id"])
                conn.execute(
                    "DELETE FROM balancer_members WHERE balancer_id = ?",
                    (balancer_id,),
                )

            for fingerprint in member_fingerprints:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO balancer_members (balancer_id, inbound_fingerprint)
                    VALUES (?, ?)
                    """,
                    (balancer_id, fingerprint),
                )
            conn.commit()
        return balancer_id

    def update_balancer(
        self,
        tag: str,
        *,
        remarks: str | None = None,
        strategy: str | None = None,
        scope: str | None = None,
        scope_target: str | None = None,
        member_fingerprints: list[str] | None = None,
    ) -> bool:
        balancer = self.get_balancer_by_tag(tag)
        if balancer is None:
            return False

        new_remarks = remarks if remarks is not None else balancer.remarks
        new_strategy = (
            normalize_strategy(strategy) if strategy is not None else balancer.strategy
        )
        new_scope = normalize_scope(scope) if scope is not None else balancer.scope
        new_target = (
            scope_target.strip()
            if scope_target is not None
            else balancer.scope_target
        )
        if new_scope in ("disabled", "all"):
            new_target = ""

        with self._db.connect() as conn:
            conn.execute(
                """
                UPDATE balancers
                SET remarks = ?, strategy = ?, scope = ?, scope_target = ?
                WHERE tag = ?
                """,
                (new_remarks, new_strategy, new_scope, new_target, tag),
            )

            if member_fingerprints is not None:
                row = conn.execute(
                    "SELECT id FROM balancers WHERE tag = ?",
                    (tag,),
                ).fetchone()
                balancer_id = int(row["id"])
                conn.execute(
                    "DELETE FROM balancer_members WHERE balancer_id = ?",
                    (balancer_id,),
                )
                for fingerprint in member_fingerprints:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO balancer_members (balancer_id, inbound_fingerprint)
                        VALUES (?, ?)
                        """,
                        (balancer_id, fingerprint),
                    )
            conn.commit()
        return True

    def set_balancer_scope(
        self,
        tag: str,
        scope: str,
        scope_target: str = "",
    ) -> bool:
        return self.update_balancer(tag, scope=scope, scope_target=scope_target)

    def delete_balancer(self, tag: str) -> bool:
        with self._db.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM balancers WHERE tag = ?",
                (tag,),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_balancers(self) -> list[BalancerRecord]:
        with self._db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, tag, remarks, strategy, scope, scope_target
                FROM balancers
                ORDER BY tag
                """
            ).fetchall()

            records: list[BalancerRecord] = []
            for row in rows:
                members = conn.execute(
                    """
                    SELECT inbound_fingerprint
                    FROM balancer_members
                    WHERE balancer_id = ?
                    ORDER BY inbound_fingerprint
                    """,
                    (row["id"],),
                ).fetchall()
                records.append(
                    BalancerRecord(
                        id=int(row["id"]),
                        tag=str(row["tag"]),
                        remarks=str(row["remarks"]),
                        strategy=str(row["strategy"]),
                        scope=normalize_scope(str(row["scope"])),
                        scope_target=str(row["scope_target"]),
                        member_fingerprints=[
                            str(member["inbound_fingerprint"]) for member in members
                        ],
                    )
                )
        return records

    def get_balancer_by_tag(self, tag: str) -> BalancerRecord | None:
        for balancer in self.list_balancers():
            if balancer.tag == tag:
                return balancer
        return None

    def has_balancers(self) -> bool:
        with self._db.connect() as conn:
            row = conn.execute("SELECT 1 FROM balancers LIMIT 1").fetchone()
        return row is not None

    def upsert_clients(self, clients: list[ClientRecord]) -> tuple[int, int]:
        now = datetime.now(timezone.utc).isoformat()
        seen: set[str] = set()
        upserted = 0

        with self._db.connect() as conn:
            for client in clients:
                seen.add(client.sub_id)
                conn.execute(
                    """
                    INSERT INTO client_index (sub_id, group_name, email, enable, last_seen_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(sub_id) DO UPDATE SET
                        group_name = excluded.group_name,
                        email = excluded.email,
                        enable = excluded.enable,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        client.sub_id,
                        client.group_name,
                        client.email,
                        1 if client.enable else 0,
                        now,
                    ),
                )
                upserted += 1

            if seen:
                placeholders = ",".join("?" for _ in seen)
                removed = conn.execute(
                    f"DELETE FROM client_index WHERE sub_id NOT IN ({placeholders})",
                    tuple(seen),
                ).rowcount
            else:
                removed = conn.execute("DELETE FROM client_index").rowcount

            conn.commit()

        return upserted, removed

    def get_group_for_sub_id(self, sub_id: str) -> str | None:
        with self._db.connect() as conn:
            row = conn.execute(
                """
                SELECT group_name
                FROM client_index
                WHERE sub_id = ? AND enable = 1
                """,
                (sub_id,),
            ).fetchone()
        if not row:
            return None
        group_name = str(row["group_name"]).strip()
        return group_name or None

    def list_clients_by_group(self, group_name: str) -> list[ClientRecord]:
        with self._db.connect() as conn:
            rows = conn.execute(
                """
                SELECT sub_id, group_name, email, enable
                FROM client_index
                WHERE group_name = ?
                ORDER BY email, sub_id
                """,
                (group_name,),
            ).fetchall()
        return [
            ClientRecord(
                sub_id=str(row["sub_id"]),
                group_name=str(row["group_name"]),
                email=str(row["email"]),
                enable=bool(row["enable"]),
            )
            for row in rows
        ]

    def upsert_panel_groups(self, group_names: list[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        seen = {name.strip() for name in group_names if name.strip()}

        with self._db.connect() as conn:
            for group_name in sorted(seen):
                conn.execute(
                    """
                    INSERT INTO panel_groups (group_name, last_seen_at)
                    VALUES (?, ?)
                    ON CONFLICT(group_name) DO UPDATE SET
                        last_seen_at = excluded.last_seen_at
                    """,
                    (group_name, now),
                )

            if seen:
                placeholders = ",".join("?" for _ in seen)
                conn.execute(
                    f"DELETE FROM panel_groups WHERE group_name NOT IN ({placeholders})",
                    tuple(seen),
                )
            else:
                conn.execute("DELETE FROM panel_groups")

            conn.commit()

    def list_groups(self) -> list[str]:
        with self._db.connect() as conn:
            rows = conn.execute(
                """
                SELECT group_name
                FROM panel_groups
                ORDER BY group_name
                """
            ).fetchall()
        return [str(row["group_name"]) for row in rows]

    def list_all_clients(self, *, enabled_only: bool = True) -> list[ClientRecord]:
        query = "SELECT sub_id, group_name, email, enable FROM client_index"
        if enabled_only:
            query += " WHERE enable = 1"
        query += " ORDER BY email, sub_id"

        with self._db.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [
            ClientRecord(
                sub_id=str(row["sub_id"]),
                group_name=str(row["group_name"]),
                email=str(row["email"]),
                enable=bool(row["enable"]),
            )
            for row in rows
        ]

    def get_balancer_tags_for_sub_id(self, sub_id: str) -> list[str]:
        tags: list[str] = []
        seen: set[str] = set()

        def _append_active(rows: list[sqlite3.Row]) -> None:
            for row in rows:
                tag = str(row["tag"])
                if tag in seen:
                    continue
                balancer = self.get_balancer_by_tag(tag)
                if balancer and balancer.member_fingerprints:
                    tags.append(tag)
                    seen.add(tag)

        with self._db.connect() as conn:
            _append_active(
                conn.execute(
                    """
                    SELECT tag FROM balancers
                    WHERE scope = 'client' AND scope_target = ?
                    ORDER BY tag
                    """,
                    (sub_id,),
                ).fetchall()
            )

            group_name = self.get_group_for_sub_id(sub_id)
            if group_name:
                _append_active(
                    conn.execute(
                        """
                        SELECT tag FROM balancers
                        WHERE scope = 'group' AND scope_target = ?
                        ORDER BY tag
                        """,
                        (group_name,),
                    ).fetchall()
                )

            _append_active(
                conn.execute(
                    """
                    SELECT tag FROM balancers
                    WHERE scope = 'all'
                    ORDER BY tag
                    """
                ).fetchall()
            )

        return tags

    def get_balancer_tag_for_sub_id(self, sub_id: str) -> str | None:
        tags = self.get_balancer_tags_for_sub_id(sub_id)
        return tags[0] if tags else None

    def assign_group_balancer(self, group_name: str, balancer_tag: str) -> None:
        if self.get_balancer_by_tag(balancer_tag) is None:
            raise ValueError(f"balancer '{balancer_tag}' not found")
        if not self.set_balancer_scope(balancer_tag, "group", group_name):
            raise ValueError(f"balancer '{balancer_tag}' not found")

    def unassign_group_balancer(
        self,
        group_name: str,
        *,
        balancer_tag: str | None = None,
    ) -> bool:
        with self._db.connect() as conn:
            if balancer_tag:
                cursor = conn.execute(
                    """
                    UPDATE balancers
                    SET scope = 'disabled', scope_target = ''
                    WHERE scope = 'group' AND scope_target = ? AND tag = ?
                    """,
                    (group_name, balancer_tag),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE balancers
                    SET scope = 'disabled', scope_target = ''
                    WHERE scope = 'group' AND scope_target = ?
                    """,
                    (group_name,),
                )
            conn.commit()
        return cursor.rowcount > 0

    def list_balancers_for_group(self, group_name: str) -> list[str]:
        with self._db.connect() as conn:
            rows = conn.execute(
                """
                SELECT tag FROM balancers
                WHERE scope = 'group' AND scope_target = ?
                ORDER BY tag
                """,
                (group_name,),
            ).fetchall()
        return [str(row["tag"]) for row in rows]

    def get_balancer_for_group(self, group_name: str) -> str | None:
        tags = self.list_balancers_for_group(group_name)
        return tags[0] if tags else None

    def list_group_assignments(self) -> list[GroupAssignment]:
        with self._db.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    b.scope_target AS group_name,
                    b.tag AS balancer_tag,
                    COUNT(ci.sub_id) AS client_count
                FROM balancers b
                LEFT JOIN client_index ci
                    ON ci.group_name = b.scope_target AND ci.enable = 1
                WHERE b.scope = 'group' AND b.scope_target != ''
                GROUP BY b.scope_target, b.tag
                ORDER BY b.scope_target
                """
            ).fetchall()
        return [
            GroupAssignment(
                group_name=str(row["group_name"]),
                balancer_tag=str(row["balancer_tag"]),
                client_count=int(row["client_count"]),
            )
            for row in rows
        ]