"""Хранилище заявок, собранных в Telegram и в Web App."""

import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from config import DB_NAME


def _backup_database() -> None:
    """Копия базы перед изменением схемы: данные заявок терять нельзя."""
    source = Path(DB_NAME)
    if source.exists() and source.stat().st_size:
        suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copyfile(source, f"{DB_NAME}.bak.{suffix}")


def init_db() -> None:
    with closing(sqlite3.connect(DB_NAME)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(hybrid_leads)")}
        # Старая база без времени согласия: колонка добавляется, заявки остаются.
        needs_consent = bool(columns) and "consent_at" not in columns
        if needs_consent:
            _backup_database()
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS hybrid_leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    lead_type TEXT NOT NULL,
                    car_interest TEXT,
                    phone TEXT,
                    created_at TEXT NOT NULL,
                    consent_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            if needs_consent:
                connection.execute(
                    "ALTER TABLE hybrid_leads ADD COLUMN consent_at TEXT NOT NULL DEFAULT ''"
                )


def save_lead(user_id: int, username: str | None, lead_type: str, car_interest: str, phone: str) -> None:
    """Заявка сюда попадает только с согласием на обработку персональных данных,
    поэтому время согласия совпадает со временем заявки."""
    now = datetime.now().isoformat(timespec="seconds")
    with closing(sqlite3.connect(DB_NAME)) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO hybrid_leads
                    (user_id, username, lead_type, car_interest, phone, created_at, consent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, lead_type, car_interest, phone, now, now),
            )
