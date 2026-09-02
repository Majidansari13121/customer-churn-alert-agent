"""Read-only SQLite access.

Connections are thread-local because sqlite3 objects cannot cross threads, and
LangGraph runs sync tools in an executor once anything async is involved.
"""

from __future__ import annotations

import os
import sqlite3
import threading

_local = threading.local()
_configured_path: str | None = None


def configure(path: str) -> None:
    """Point the package at a database file. Call once, before any query."""
    global _configured_path
    if not os.path.exists(path):
        raise SystemExit(
            f"Database not found: {path}\n"
            "  Create it with: uv run python quick_commerce_sim.py init"
        )
    _configured_path = path


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    if _configured_path is None:
        raise RuntimeError("db.configure(path) must be called before querying.")

    # mode=ro plus query_only: the agent has no business writing here, and a
    # read-only handle means a bad query fails loudly instead of mutating data.
    conn = sqlite3.connect(
        f"file:{_configured_path}?mode=ro", uri=True, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    _local.conn = conn
    return conn


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return get_conn().execute(sql, params).fetchall()


def customer_ids() -> list[int]:
    return [r["user_id"] for r in query(
        "SELECT user_id FROM users WHERE user_type='CUSTOMER' ORDER BY user_id"
    )]


def customer_names() -> dict[int, str]:
    """user_id -> display name. Joined once, late, only for the final report."""
    return {
        r["user_id"]: f"{r['full_name']} ({r['city']})"
        for r in query(
            "SELECT user_id, full_name, city FROM users WHERE user_type='CUSTOMER'"
        )
    }
