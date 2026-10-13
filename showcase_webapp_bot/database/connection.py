"""Соединение с SQLite и общие мелочи для запросов."""

import sqlite3
from datetime import datetime, timezone

import config


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(config.DB_NAME)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}
