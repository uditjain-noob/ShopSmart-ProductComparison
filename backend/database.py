"""Persistence helpers for users, saved lists, and saved comparisons."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

_SQLITE_CONN: sqlite3.Connection | None = None
_LOCK = threading.Lock()


class SimpleCursor:
    def __init__(self, columns: list[str], rows: list[tuple[Any, ...]]):
        self.description = [(column,) for column in columns]
        self._rows = rows
        self._index = 0

    def fetchall(self) -> list[tuple[Any, ...]]:
        remaining = self._rows[self._index :]
        self._index = len(self._rows)
        return remaining

    def fetchone(self) -> tuple[Any, ...] | None:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _use_turso() -> bool:
    return bool(os.getenv("TURSO_DATABASE_URL") and os.getenv("TURSO_AUTH_TOKEN"))


def _turso_endpoint() -> str:
    url = os.environ["TURSO_DATABASE_URL"].strip()
    if url.startswith("libsql://"):
        url = "https://" + url.removeprefix("libsql://")
    return url.rstrip("/") + "/v2/pipeline"


def _encode_arg(value: Any) -> dict[str, str]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": str(value)}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
    return {"type": "text", "value": str(value)}


def _decode_value(value: dict[str, Any]) -> Any:
    value_type = value.get("type")
    if value_type == "null":
        return None
    if value_type == "integer":
        return int(value.get("value", "0"))
    if value_type == "float":
        return float(value.get("value", "0"))
    if value_type == "blob":
        return base64.b64decode(value.get("base64", ""))
    return value.get("value")


def _execute_turso(sql: str, params: tuple[Any, ...] = ()) -> SimpleCursor:
    response = requests.post(
        _turso_endpoint(),
        headers={
            "Authorization": f"Bearer {os.environ['TURSO_AUTH_TOKEN']}",
            "Content-Type": "application/json",
        },
        json={
            "requests": [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": sql,
                        "args": [_encode_arg(param) for param in params],
                    },
                },
                {"type": "close"},
            ]
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    first = payload["results"][0]
    if first.get("type") == "error":
        error = first.get("error", {})
        raise RuntimeError(error.get("message") or "Turso query failed")

    result = first.get("response", {}).get("result", {})
    columns = [column.get("name", "") for column in result.get("cols", [])]
    rows = [
        tuple(_decode_value(value) for value in row)
        for row in result.get("rows", [])
    ]
    return SimpleCursor(columns, rows)


def _sqlite_conn() -> sqlite3.Connection:
    global _SQLITE_CONN
    if _SQLITE_CONN is None:
        db_path = Path(os.getenv("LOCAL_DATABASE_PATH", "shopsmart.db"))
        _SQLITE_CONN = sqlite3.connect(db_path, check_same_thread=False)
    return _SQLITE_CONN


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [col[0] for col in (cursor.description or [])]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def execute(sql: str, params: tuple[Any, ...] = ()) -> Any:
    with _LOCK:
        if _use_turso():
            return _execute_turso(sql, params)
        return _sqlite_conn().execute(sql, params)


def execute_write(sql: str, params: tuple[Any, ...] = ()) -> Any:
    with _LOCK:
        if _use_turso():
            return _execute_turso(sql, params)
        conn = _sqlite_conn()
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor


def executemany_write(sql: str, rows: list[tuple[Any, ...]]) -> None:
    if not rows:
        return
    with _LOCK:
        if _use_turso():
            for row in rows:
                _execute_turso(sql, row)
            return
        conn = _sqlite_conn()
        conn.executemany(sql, rows)
        conn.commit()


def init_db() -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            hashed_pw TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS saved_lists (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS list_products (
            id TEXT PRIMARY KEY,
            list_id TEXT NOT NULL REFERENCES saved_lists(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            platform TEXT NOT NULL,
            title TEXT,
            selected INTEGER NOT NULL DEFAULT 1,
            position INTEGER NOT NULL DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS saved_comparisons (
            id TEXT PRIMARY KEY,
            list_id TEXT REFERENCES saved_lists(id) ON DELETE SET NULL,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            summary TEXT,
            recommendation TEXT,
            markdown TEXT,
            questionnaire_json TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS comparison_products (
            id TEXT PRIMARY KEY,
            comparison_id TEXT NOT NULL REFERENCES saved_comparisons(id) ON DELETE CASCADE,
            profile_json TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0
        )
        """,
    ]
    for statement in statements:
        execute_write(statement)


def create_user(email: str, hashed_pw: str) -> dict[str, Any]:
    user = {"id": _new_id(), "email": email.lower().strip(), "created_at": _now()}
    execute_write(
        "INSERT INTO users (id, email, hashed_pw, created_at) VALUES (?, ?, ?, ?)",
        (user["id"], user["email"], hashed_pw, user["created_at"]),
    )
    return user


def get_user_by_email(email: str) -> dict[str, Any] | None:
    rows = _rows(execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)))
    return rows[0] if rows else None


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    rows = _rows(execute("SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)))
    return rows[0] if rows else None


def user_owns_list(user_id: str, list_id: str) -> bool:
    return bool(execute("SELECT 1 FROM saved_lists WHERE id = ? AND user_id = ?", (list_id, user_id)).fetchone())


def save_list(
    user_id: str,
    name: str,
    products: list[dict[str, Any]],
    list_id: str | None = None,
) -> dict[str, Any]:
    now = _now()
    if list_id:
        if not user_owns_list(user_id, list_id):
            raise KeyError("List not found")
        execute_write(
            "UPDATE saved_lists SET name = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (name, now, list_id, user_id),
        )
        execute_write("DELETE FROM list_products WHERE list_id = ?", (list_id,))
    else:
        list_id = _new_id()
        execute_write(
            "INSERT INTO saved_lists (id, user_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (list_id, user_id, name, now, now),
        )

    product_rows = [
        (
            _new_id(),
            list_id,
            product["url"],
            product.get("platform") or "Unknown",
            product.get("title"),
            1 if product.get("selected", True) else 0,
            index,
        )
        for index, product in enumerate(products)
    ]
    executemany_write(
        """
        INSERT INTO list_products (id, list_id, url, platform, title, selected, position)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        product_rows,
    )
    return get_list(user_id, list_id) or {"id": list_id, "name": name, "products": []}


def get_all_lists(user_id: str) -> list[dict[str, Any]]:
    return _rows(execute(
        """
        SELECT sl.id, sl.name, sl.created_at, sl.updated_at, COUNT(lp.id) AS product_count
        FROM saved_lists sl
        LEFT JOIN list_products lp ON lp.list_id = sl.id
        WHERE sl.user_id = ?
        GROUP BY sl.id
        ORDER BY sl.updated_at DESC
        """,
        (user_id,),
    ))


def get_list(user_id: str, list_id: str) -> dict[str, Any] | None:
    rows = _rows(execute(
        "SELECT id, name, created_at, updated_at FROM saved_lists WHERE id = ? AND user_id = ?",
        (list_id, user_id),
    ))
    if not rows:
        return None
    saved = rows[0]
    products = _rows(execute(
        """
        SELECT id, url, platform, title, selected, position
        FROM list_products
        WHERE list_id = ?
        ORDER BY position ASC
        """,
        (list_id,),
    ))
    for product in products:
        product["selected"] = bool(product["selected"])
    saved["products"] = products
    return saved


def delete_list(user_id: str, list_id: str) -> bool:
    if not user_owns_list(user_id, list_id):
        return False
    execute_write("UPDATE saved_comparisons SET list_id = NULL WHERE list_id = ? AND user_id = ?", (list_id, user_id))
    execute_write("DELETE FROM list_products WHERE list_id = ?", (list_id,))
    execute_write("DELETE FROM saved_lists WHERE id = ? AND user_id = ?", (list_id, user_id))
    return True


def get_product_urls_for_list(user_id: str, list_id: str, product_ids: list[str] | None = None) -> list[str]:
    if not user_owns_list(user_id, list_id):
        raise KeyError("List not found")
    if product_ids:
        placeholders = ",".join("?" for _ in product_ids)
        rows = _rows(execute(
            f"SELECT url FROM list_products WHERE list_id = ? AND id IN ({placeholders}) ORDER BY position ASC",
            (list_id, *product_ids),
        ))
    else:
        rows = _rows(execute(
            "SELECT url FROM list_products WHERE list_id = ? ORDER BY position ASC",
            (list_id,),
        ))
    return [row["url"] for row in rows]


def _profile_to_dict(profile: Any) -> dict[str, Any]:
    return {
        "title": profile.title,
        "price": profile.price,
        "platform": profile.platform,
        "specs": profile.specs,
        "description_summary": profile.description_summary,
        "pros": profile.pros,
        "cons": profile.cons,
        "sentiment_score": profile.sentiment_score,
        "notable_quotes": profile.notable_quotes,
    }


def save_comparison(
    user_id: str,
    list_id: str | None,
    result: dict[str, Any],
    profiles: list[Any] | None = None,
) -> str:
    if list_id and not user_owns_list(user_id, list_id):
        raise KeyError("List not found")

    comparison_id = _new_id()
    execute_write(
        """
        INSERT INTO saved_comparisons
            (id, list_id, user_id, created_at, summary, recommendation, markdown, questionnaire_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            comparison_id,
            list_id,
            user_id,
            _now(),
            result.get("summary"),
            result.get("recommendation"),
            result.get("markdown"),
            json.dumps(result.get("questionnaire") or {"questions": []}),
        ),
    )

    products = [_profile_to_dict(profile) for profile in profiles] if profiles else result.get("products") or []
    executemany_write(
        """
        INSERT INTO comparison_products (id, comparison_id, profile_json, position)
        VALUES (?, ?, ?, ?)
        """,
        [(_new_id(), comparison_id, json.dumps(product), index) for index, product in enumerate(products)],
    )
    return comparison_id


def get_comparisons_for_list(user_id: str, list_id: str) -> list[dict[str, Any]]:
    if not user_owns_list(user_id, list_id):
        raise KeyError("List not found")
    return _rows(execute(
        """
        SELECT sc.id, sc.list_id, sc.created_at, sc.summary, sc.recommendation,
               COUNT(cp.id) AS product_count
        FROM saved_comparisons sc
        LEFT JOIN comparison_products cp ON cp.comparison_id = sc.id
        WHERE sc.user_id = ? AND sc.list_id = ?
        GROUP BY sc.id
        ORDER BY sc.created_at DESC
        """,
        (user_id, list_id),
    ))


def get_all_comparisons(user_id: str) -> list[dict[str, Any]]:
    return _rows(execute(
        """
        SELECT sc.id, sc.list_id, sc.created_at, sc.summary, sc.recommendation,
               sl.name AS list_name, COUNT(cp.id) AS product_count
        FROM saved_comparisons sc
        LEFT JOIN saved_lists sl ON sl.id = sc.list_id
        LEFT JOIN comparison_products cp ON cp.comparison_id = sc.id
        WHERE sc.user_id = ?
        GROUP BY sc.id
        ORDER BY sc.created_at DESC
        """,
        (user_id,),
    ))


def get_comparison(user_id: str, comparison_id: str) -> dict[str, Any] | None:
    rows = _rows(execute(
        """
        SELECT sc.*, sl.name AS list_name
        FROM saved_comparisons sc
        LEFT JOIN saved_lists sl ON sl.id = sc.list_id
        WHERE sc.id = ? AND sc.user_id = ?
        """,
        (comparison_id, user_id),
    ))
    if not rows:
        return None

    comparison = rows[0]
    product_rows = _rows(execute(
        """
        SELECT profile_json
        FROM comparison_products
        WHERE comparison_id = ?
        ORDER BY position ASC
        """,
        (comparison_id,),
    ))
    comparison["products"] = [json.loads(row["profile_json"]) for row in product_rows]
    comparison["questionnaire"] = json.loads(comparison.pop("questionnaire_json") or '{"questions":[]}')
    return comparison
