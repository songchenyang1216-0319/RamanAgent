"""Small sqlite repository helpers used by the productized storage layer."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from backend.db.session import session_scope


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def dumps_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def loads_json(value: Any, default: Any = None) -> Any:
    if value in {None, ""}:
        return default
    try:
        return json.loads(str(value))
    except Exception:
        return default


class SQLiteRepository:
    table_name: str = ""
    id_field: str = ""

    def __init__(self, table_name: str | None = None, id_field: str | None = None) -> None:
        self.table_name = table_name or self.table_name
        self.id_field = id_field or self.id_field
        if not self.table_name or not self.id_field:
            raise ValueError("Repository 需要 table_name 和 id_field。")

    def create(self, payload: dict[str, Any], *, id_value: str | None = None) -> dict[str, Any]:
        now = now_iso()
        item = dict(payload or {})
        item.setdefault(self.id_field, id_value or uuid4().hex)
        item.setdefault("created_at", now)
        item.setdefault("updated_at", now)
        columns = list(item.keys())
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT OR REPLACE INTO {self.table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        with session_scope() as connection:
            connection.execute(sql, [item[column] for column in columns])
        return item

    def update(self, item_id: str, **changes: Any) -> dict[str, Any] | None:
        if not changes:
            return self.get(item_id)
        changes["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in changes.keys())
        with session_scope() as connection:
            connection.execute(
                f"UPDATE {self.table_name} SET {assignments} WHERE {self.id_field} = ?",
                [*changes.values(), item_id],
            )
        return self.get(item_id)

    def get(self, item_id: str) -> dict[str, Any] | None:
        with session_scope() as connection:
            row = connection.execute(
                f"SELECT * FROM {self.table_name} WHERE {self.id_field} = ?",
                (item_id,),
            ).fetchone()
        return dict(row) if row else None

    def list(self, *, user_id: str | None = None, limit: int = 100, order_by: str = "created_at DESC") -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 100), 500))
        where = ""
        params: list[Any] = []
        if user_id:
            where = "WHERE user_id = ?"
            params.append(user_id)
        with session_scope() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self.table_name} {where} ORDER BY {order_by} LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [dict(row) for row in rows]

