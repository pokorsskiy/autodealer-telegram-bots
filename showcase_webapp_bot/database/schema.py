"""Схема базы и миграции: недостающие таблицы и колонки добавляются без потери данных."""

import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import config
from database.connection import connect, table_columns, table_exists
from database.seed import localize_demo_images, seed_catalog

LEAD_EXTRA_COLUMNS = {
    "lead_type": "TEXT NOT NULL DEFAULT 'car'",
    "contact_username": "TEXT",
    "car_id": "TEXT",
    # Заявка приходит либо из Telegram, либо из витрины, открытой в браузере.
    "source": "TEXT NOT NULL DEFAULT 'telegram'",
    "status": "TEXT NOT NULL DEFAULT 'new'",
    "note": "TEXT NOT NULL DEFAULT ''",
    "handled_by": "TEXT NOT NULL DEFAULT ''",
    # Архив прячет заявку из рабочего списка, но ничего не удаляет.
    "is_archived": "INTEGER NOT NULL DEFAULT 0",
    # Когда клиент дал согласие на обработку персональных данных; у заявок,
    # принятых до появления галочки, пусто.
    "consent_at": "TEXT NOT NULL DEFAULT ''",
}


CAR_EXTRA_COLUMNS = {
    "is_sold": "INTEGER NOT NULL DEFAULT 0",
    "sold_at": "TEXT NOT NULL DEFAULT ''",
}

ADMIN_USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('developer', 'owner', 'manager')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL
)
"""


def _backup_database() -> None:
    source = Path(config.DB_NAME)
    backup = Path(f"{config.DB_NAME}.bak")
    if not source.exists() or not source.stat().st_size:
        return
    if backup.exists():
        suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = Path(f"{config.DB_NAME}.bak.{suffix}")
    shutil.copyfile(source, backup)


def _needs_migration(connection: sqlite3.Connection) -> bool:
    if not table_exists(connection, "webapp_leads"):
        return False
    missing_lead_columns = set(LEAD_EXTRA_COLUMNS) - table_columns(
        connection, "webapp_leads"
    )
    missing_car_columns = (
        set(CAR_EXTRA_COLUMNS) - table_columns(connection, "catalog_cars")
        if table_exists(connection, "catalog_cars")
        else set()
    )
    return bool(missing_lead_columns or missing_car_columns) or not all(
        table_exists(connection, table)
        for table in ("catalog_cars", "car_images", "admin_users", "admin_actions")
    )


def _migrate_leads(connection: sqlite3.Connection) -> None:
    columns = table_columns(connection, "webapp_leads")
    for name, definition in LEAD_EXTRA_COLUMNS.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE webapp_leads ADD COLUMN {name} {definition}"
            )


def _migrate_cars(connection: sqlite3.Connection) -> None:
    columns = table_columns(connection, "catalog_cars")
    for name, definition in CAR_EXTRA_COLUMNS.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE catalog_cars ADD COLUMN {name} {definition}"
            )


def _migrate_admin_roles(connection: sqlite3.Connection) -> None:
    """Роль «разработчик» не проходит старое ограничение CHECK.

    В SQLite ограничение нельзя изменить на месте, поэтому таблица
    пересобирается с новым списком ролей, а записи переносятся как есть.
    """
    definition = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'admin_users'"
    ).fetchone()
    if not definition or "developer" in str(definition["sql"]):
        return
    connection.execute("ALTER TABLE admin_users RENAME TO admin_users_old")
    connection.execute(ADMIN_USERS_SCHEMA)
    connection.execute(
        """
        INSERT INTO admin_users (
            id, username, password_hash, role, is_active, created_at
        )
        SELECT id, username, password_hash, role, is_active, created_at
        FROM admin_users_old
        """
    )
    connection.execute("DROP TABLE admin_users_old")


def init_db() -> None:
    Path(config.DB_NAME).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as connection:
        if _needs_migration(connection):
            _backup_database()
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS webapp_leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    car_interest TEXT NOT NULL,
                    purchase_method TEXT NOT NULL,
                    comment TEXT,
                    created_at TEXT NOT NULL,
                    lead_type TEXT NOT NULL DEFAULT 'car',
                    contact_username TEXT,
                    car_id TEXT,
                    source TEXT NOT NULL DEFAULT 'telegram',
                    status TEXT NOT NULL DEFAULT 'new',
                    note TEXT NOT NULL DEFAULT '',
                    handled_by TEXT NOT NULL DEFAULT '',
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    consent_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            _migrate_leads(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS catalog_cars (
                    id TEXT PRIMARY KEY,
                    brand TEXT NOT NULL,
                    model TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    mileage INTEGER NOT NULL DEFAULT 0,
                    body TEXT NOT NULL,
                    drive TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    power TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL CHECK (location IN ('city', 'port')),
                    is_visible INTEGER NOT NULL DEFAULT 1 CHECK (is_visible IN (0, 1)),
                    is_sold INTEGER NOT NULL DEFAULT 0 CHECK (is_sold IN (0, 1)),
                    sold_at TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            _migrate_cars(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS car_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    car_id TEXT NOT NULL REFERENCES catalog_cars(id) ON DELETE CASCADE,
                    url TEXT NOT NULL,
                    alt_text TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(ADMIN_USERS_SCHEMA)
            _migrate_admin_roles(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    username TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT '',
                    details TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            seed_catalog(connection)
            localize_demo_images(connection)
