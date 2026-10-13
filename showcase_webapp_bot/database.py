"""SQLite-хранилище заявок, каталога и пользователей веб-админки."""

import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DB_NAME

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

LEAD_STATUSES = ("new", "in_work", "won", "lost")

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

LEAD_FIELDS = (
    "id",
    "user_id",
    "username",
    "name",
    "phone",
    "car_interest",
    "purchase_method",
    "comment",
    "created_at",
    "lead_type",
    "contact_username",
    "car_id",
    "source",
    "status",
    "note",
    "handled_by",
    "is_archived",
    "consent_at",
)

CAR_FIELDS = (
    "id",
    "brand",
    "model",
    "year",
    "price",
    "mileage",
    "body",
    "drive",
    "engine",
    "power",
    "description",
    "location",
    "is_visible",
    "sort_order",
)

DEMO_CARS = (
    {
        "id": "toyota-camry-2024",
        "brand": "Toyota",
        "model": "Camry",
        "year": 2024,
        "price": 3_850_000,
        "mileage": 8_000,
        "body": "Седан",
        "drive": "Передний",
        "engine": "2.5 л · бензин",
        "power": "203 л.с.",
        "description": "Комфортный седан для города и трассы с просторным салоном и современными ассистентами.",
        "location": "city",
        "images": (
            "/demo/toyota-camry.png",
        ),
    },
    {
        "id": "bmw-x5-2023",
        "brand": "BMW",
        "model": "X5",
        "year": 2023,
        "price": 8_900_000,
        "mileage": 24_000,
        "body": "Кроссовер",
        "drive": "Полный",
        "engine": "3.0 л · дизель",
        "power": "298 л.с.",
        "description": "Премиальный кроссовер с полным приводом и высоким уровнем комфорта для дальних поездок.",
        "location": "port",
        "images": (
            "/demo/bmw-x5.jpg",
        ),
    },
    {
        "id": "geely-monjaro-2025",
        "brand": "Geely",
        "model": "Monjaro",
        "year": 2025,
        "price": 4_650_000,
        "mileage": 2_000,
        "body": "Кроссовер",
        "drive": "Полный",
        "engine": "2.0 л · бензин",
        "power": "238 л.с.",
        "description": "Современный семейный кроссовер с просторным салоном и богатым набором электронных помощников.",
        "location": "port",
        "images": (
            "/demo/geely-monjaro.png",
        ),
    },
    {
        "id": "audi-q5-2023",
        "brand": "Audi",
        "model": "Q5",
        "year": 2023,
        "price": 7_450_000,
        "mileage": 31_000,
        "body": "Кроссовер",
        "drive": "Полный",
        "engine": "2.0 л · бензин",
        "power": "265 л.с.",
        "description": (
            "Сбалансированный премиальный кроссовер с quattro и удобным размером "
            "для ежедневной эксплуатации."
        ),
        "location": "city",
        "images": (
            "/demo/audi-q5.webp",
        ),
    },
    {
        "id": "kia-sorento-2024",
        "brand": "Kia",
        "model": "Sorento",
        "year": 2024,
        "price": 5_300_000,
        "mileage": 12_000,
        "body": "Внедорожник",
        "drive": "Полный",
        "engine": "2.5 л · бензин",
        "power": "281 л.с.",
        "description": "Практичный семиместный автомобиль для семьи, путешествий и повседневных задач.",
        "location": "city",
        "images": ("/demo/kia-sorento.jpg",),
    },
    {
        "id": "toyota-camry-2022",
        "brand": "Toyota",
        "model": "Camry Prestige",
        "year": 2022,
        "price": 3_300_000,
        "mileage": 54_000,
        "body": "Седан",
        "drive": "Передний",
        "engine": "2.5 л · бензин",
        "power": "200 л.с.",
        "description": "Проверенный седан в богатой комплектации с комфортной подвеской и привычной эргономикой.",
        "location": "city",
        "images": (
            "/demo/toyota-camry.png",
        ),
    },
)


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_NAME)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _backup_database() -> None:
    source = Path(DB_NAME)
    backup = Path(f"{DB_NAME}.bak")
    if not source.exists() or not source.stat().st_size:
        return
    if backup.exists():
        suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = Path(f"{DB_NAME}.bak.{suffix}")
    shutil.copyfile(source, backup)


def _needs_migration(connection: sqlite3.Connection) -> bool:
    if not _table_exists(connection, "webapp_leads"):
        return False
    missing_lead_columns = set(LEAD_EXTRA_COLUMNS) - _table_columns(
        connection, "webapp_leads"
    )
    missing_car_columns = (
        set(CAR_EXTRA_COLUMNS) - _table_columns(connection, "catalog_cars")
        if _table_exists(connection, "catalog_cars")
        else set()
    )
    return bool(missing_lead_columns or missing_car_columns) or not all(
        _table_exists(connection, table)
        for table in ("catalog_cars", "car_images", "admin_users", "admin_actions")
    )


def _migrate_leads(connection: sqlite3.Connection) -> None:
    columns = _table_columns(connection, "webapp_leads")
    for name, definition in LEAD_EXTRA_COLUMNS.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE webapp_leads ADD COLUMN {name} {definition}"
            )


def _migrate_cars(connection: sqlite3.Connection) -> None:
    columns = _table_columns(connection, "catalog_cars")
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


# Раньше демо-фото ссылались на чужие сайты и пропадали вместе с ними.
# Теперь они лежат в web/demo/, а старые адреса в готовых базах заменяются.
DEMO_IMAGE_MOVES = {
    "https://di-uploads-pod10.dealerinspire.com/wilsonvilletoyota/uploads/2023/09/2024camry-1.png":
        "/demo/toyota-camry.png",
    "https://cdn.bimmertoday.de/wp-content/uploads/2023/02/2023-BMW-X5-Facelift-G05-LCI-xLine-Blue-Ridge-Mountain-xDrive50e-42.jpg":
        "/demo/bmw-x5.jpg",
    "https://www.geely.com/-/media/project/web-portal/models/new-monjaro/360-colors/green/green-0.png?h=535&hash=34D9485C11C1E9A5058F48381468D19A&iar=0&w=1500":
        "/demo/geely-monjaro.png",
    "https://images3.kingautos.net/spec/2023/01/kZ6Ro5Oeop2RnpGgmco.webp":
        "/demo/audi-q5.webp",
    "https://www.kiamedia.com/image/landing/21417/1/2/21773?v=3":
        "/demo/kia-sorento.jpg",
}


def _localize_demo_images(connection: sqlite3.Connection) -> None:
    for old_url, new_url in DEMO_IMAGE_MOVES.items():
        connection.execute(
            "UPDATE car_images SET url = ? WHERE url = ?", (new_url, old_url)
        )


def _seed_catalog(connection: sqlite3.Connection) -> None:
    count = connection.execute("SELECT COUNT(*) FROM catalog_cars").fetchone()[0]
    if count:
        return
    now = _utc_now()
    for index, car in enumerate(DEMO_CARS):
        connection.execute(
            """
            INSERT INTO catalog_cars (
                id, brand, model, year, price, mileage, body, drive, engine,
                power, description, location, is_visible, sort_order,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                car["id"],
                car["brand"],
                car["model"],
                car["year"],
                car["price"],
                car["mileage"],
                car["body"],
                car["drive"],
                car["engine"],
                car["power"],
                car["description"],
                car["location"],
                index,
                now,
                now,
            ),
        )
        for image_index, image_url in enumerate(car["images"]):
            connection.execute(
                """
                INSERT INTO car_images (car_id, url, alt_text, sort_order)
                VALUES (?, ?, ?, ?)
                """,
                (
                    car["id"],
                    image_url,
                    f"{car['brand']} {car['model']}",
                    image_index,
                ),
            )


def init_db() -> None:
    Path(DB_NAME).parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect()) as connection:
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
            _seed_catalog(connection)
            _localize_demo_images(connection)


def save_lead(
    user_id: int,
    telegram_username: str | None,
    lead: dict[str, str],
    source: str = "telegram",
) -> int:
    """Сохраняет заявку и возвращает её номер для уведомления.

    Заявка сюда попадает только с согласием на обработку персональных данных,
    поэтому время согласия совпадает со временем заявки.
    """
    now = _utc_now()
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO webapp_leads (
                    user_id, username, name, phone, car_interest,
                    purchase_method, comment, created_at, lead_type,
                    contact_username, car_id, source, consent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    telegram_username,
                    lead["name"],
                    lead["phone"],
                    lead["car_interest"],
                    lead["purchase_method"],
                    lead["comment"],
                    now,
                    lead["lead_type"],
                    lead["username"],
                    lead["car_id"],
                    source,
                    now,
                ),
            )
            return int(cursor.lastrowid)


def list_leads(limit: int = 200) -> list[dict[str, Any]]:
    """Последние заявки для раздела админки: новые сверху."""
    with closing(_connect()) as connection:
        rows = connection.execute(
            """
            SELECT * FROM webapp_leads
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [{field: row[field] for field in LEAD_FIELDS} for row in rows]


def update_lead(
    lead_id: int, *, status: str, note: str, handled_by: str
) -> bool:
    """Меняет статус и заметку по заявке: работа менеджера, а не клиента."""
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                """
                UPDATE webapp_leads
                SET status = ?, note = ?, handled_by = ?
                WHERE id = ?
                """,
                (status, note, handled_by, lead_id),
            )
            return cursor.rowcount > 0


def set_lead_archived(lead_id: int, archived: bool) -> bool:
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                "UPDATE webapp_leads SET is_archived = ? WHERE id = ?",
                (int(archived), lead_id),
            )
            return cursor.rowcount > 0


def delete_lead(lead_id: int) -> bool:
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                "DELETE FROM webapp_leads WHERE id = ?", (lead_id,)
            )
            return cursor.rowcount > 0


def get_lead(lead_id: int) -> dict[str, Any] | None:
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT * FROM webapp_leads WHERE id = ?", (lead_id,)
        ).fetchone()
    return {field: row[field] for field in LEAD_FIELDS} if row else None


def set_car_sold(car_id: str, sold: bool) -> bool:
    """Проданная машина уходит из витрины, но остаётся в админке."""
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                """
                UPDATE catalog_cars
                SET is_sold = ?, sold_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(sold), _utc_now() if sold else "", _utc_now(), car_id),
            )
            return cursor.rowcount > 0


def log_action(
    admin_id: int | None, username: str, action: str, target: str = "", details: str = ""
) -> None:
    with closing(_connect()) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO admin_actions (
                    admin_id, username, action, target, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (admin_id, username, action, target, details, _utc_now()),
            )


def list_actions(limit: int = 100) -> list[dict[str, Any]]:
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM admin_actions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def delete_admin(admin_id: int) -> bool:
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                "DELETE FROM admin_users WHERE id = ?", (admin_id,)
            )
            return cursor.rowcount > 0


def catalog_summary() -> dict[str, int]:
    """Короткая сводка для первого экрана админки."""
    with closing(_connect()) as connection:
        cars = connection.execute(
            "SELECT COUNT(*) FROM catalog_cars WHERE is_sold = 0"
        ).fetchone()[0]
        hidden = connection.execute(
            "SELECT COUNT(*) FROM catalog_cars WHERE is_visible = 0 AND is_sold = 0"
        ).fetchone()[0]
        sold = connection.execute(
            "SELECT COUNT(*) FROM catalog_cars WHERE is_sold = 1"
        ).fetchone()[0]
        leads_week = connection.execute(
            """
            SELECT COUNT(*) FROM webapp_leads
            WHERE datetime(created_at) >= datetime('now', '-7 days')
            """
        ).fetchone()[0]
        leads_new = connection.execute(
            "SELECT COUNT(*) FROM webapp_leads WHERE status = 'new' AND is_archived = 0"
        ).fetchone()[0]
    return {
        "cars": cars,
        "hidden": hidden,
        "sold": sold,
        "leads_week": leads_week,
        "leads_new": leads_new,
    }


def _car_dict(row: sqlite3.Row, images: list[dict[str, Any]]) -> dict[str, Any]:
    result = {field: row[field] for field in CAR_FIELDS}
    result["is_visible"] = bool(result["is_visible"])
    result["is_sold"] = bool(row["is_sold"])
    result["sold_at"] = row["sold_at"]
    # Дата нужна витрине для отметки новых поступлений, в формы админки не идёт.
    result["created_at"] = row["created_at"]
    result["images"] = images
    return result


def list_cars(include_hidden: bool = False) -> list[dict[str, Any]]:
    where = "" if include_hidden else "WHERE is_visible = 1 AND is_sold = 0"
    with closing(_connect()) as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM catalog_cars
            {where}
            ORDER BY sort_order ASC, created_at DESC
            """
        ).fetchall()
        image_rows = connection.execute(
            """
            SELECT id, car_id, url, alt_text, sort_order
            FROM car_images
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
    images_by_car: dict[str, list[dict[str, Any]]] = {}
    for image in image_rows:
        images_by_car.setdefault(image["car_id"], []).append(dict(image))
    return [
        _car_dict(row, images_by_car.get(row["id"], []))
        for row in rows
    ]


def get_car(car_id: str) -> dict[str, Any] | None:
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT * FROM catalog_cars WHERE id = ?", (car_id,)
        ).fetchone()
        if row is None:
            return None
        images = [
            dict(image)
            for image in connection.execute(
                """
                SELECT id, car_id, url, alt_text, sort_order
                FROM car_images WHERE car_id = ?
                ORDER BY sort_order ASC, id ASC
                """,
                (car_id,),
            ).fetchall()
        ]
    return _car_dict(row, images)


def save_car(car: dict[str, Any], original_id: str | None = None) -> str:
    car_id = original_id or car["id"]
    now = _utc_now()
    with closing(_connect()) as connection:
        with connection:
            if original_id:
                connection.execute(
                    """
                    UPDATE catalog_cars SET
                        brand = ?, model = ?, year = ?, price = ?, mileage = ?,
                        body = ?, drive = ?, engine = ?, power = ?,
                        description = ?, location = ?, is_visible = ?,
                        sort_order = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        car["brand"],
                        car["model"],
                        car["year"],
                        car["price"],
                        car["mileage"],
                        car["body"],
                        car["drive"],
                        car["engine"],
                        car["power"],
                        car["description"],
                        car["location"],
                        int(car["is_visible"]),
                        car["sort_order"],
                        now,
                        original_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO catalog_cars (
                        id, brand, model, year, price, mileage, body, drive,
                        engine, power, description, location, is_visible,
                        sort_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        car_id,
                        car["brand"],
                        car["model"],
                        car["year"],
                        car["price"],
                        car["mileage"],
                        car["body"],
                        car["drive"],
                        car["engine"],
                        car["power"],
                        car["description"],
                        car["location"],
                        int(car["is_visible"]),
                        car["sort_order"],
                        now,
                        now,
                    ),
                )
    return car_id


def delete_car(car_id: str) -> list[str]:
    car = get_car(car_id)
    if car is None:
        return []
    local_urls = [
        image["url"] for image in car["images"] if image["url"].startswith("/uploads/")
    ]
    with closing(_connect()) as connection:
        with connection:
            connection.execute("DELETE FROM catalog_cars WHERE id = ?", (car_id,))
    return local_urls


def add_car_image(car_id: str, url: str, alt_text: str = "") -> int:
    with closing(_connect()) as connection:
        with connection:
            next_order = connection.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM car_images WHERE car_id = ?",
                (car_id,),
            ).fetchone()[0]
            cursor = connection.execute(
                """
                INSERT INTO car_images (car_id, url, alt_text, sort_order)
                VALUES (?, ?, ?, ?)
                """,
                (car_id, url, alt_text, next_order),
            )
            return int(cursor.lastrowid)


def delete_car_image(image_id: int) -> str | None:
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT url FROM car_images WHERE id = ?", (image_id,)
        ).fetchone()
        if row is None:
            return None
        with connection:
            connection.execute("DELETE FROM car_images WHERE id = ?", (image_id,))
        return str(row["url"])


def reorder_car_images(car_id: str, image_ids: list[int]) -> None:
    with closing(_connect()) as connection:
        existing = {
            int(row["id"])
            for row in connection.execute(
                "SELECT id FROM car_images WHERE car_id = ?", (car_id,)
            )
        }
        if set(image_ids) != existing:
            raise ValueError("Некорректный набор фотографий")
        with connection:
            for order, image_id in enumerate(image_ids):
                connection.execute(
                    "UPDATE car_images SET sort_order = ? WHERE id = ? AND car_id = ?",
                    (order, image_id, car_id),
                )


def get_admin_by_username(username: str) -> dict[str, Any] | None:
    with closing(_connect()) as connection:
        row = connection.execute(
            """
            SELECT id, username, password_hash, role, is_active
            FROM admin_users WHERE username = ?
            """,
            (username,),
        ).fetchone()
    return dict(row) if row else None


def get_admin(admin_id: int) -> dict[str, Any] | None:
    with closing(_connect()) as connection:
        row = connection.execute(
            """
            SELECT id, username, password_hash, role, is_active
            FROM admin_users WHERE id = ?
            """,
            (admin_id,),
        ).fetchone()
    return dict(row) if row else None


def _create_initial_admin(username: str, password_hash: str, role: str) -> bool:
    """Создаёт первую учётную запись роли; если такая роль уже есть — ничего."""
    with closing(_connect()) as connection:
        exists = connection.execute(
            "SELECT 1 FROM admin_users WHERE role = ? LIMIT 1", (role,)
        ).fetchone()
        taken = connection.execute(
            "SELECT 1 FROM admin_users WHERE username = ? LIMIT 1", (username,)
        ).fetchone()
        if exists or taken:
            return False
        with connection:
            connection.execute(
                """
                INSERT INTO admin_users (
                    username, password_hash, role, is_active, created_at
                ) VALUES (?, ?, ?, 1, ?)
                """,
                (username, password_hash, role, _utc_now()),
            )
        return True


def create_initial_owner(username: str, password_hash: str) -> bool:
    return _create_initial_admin(username, password_hash, "owner")


def create_initial_developer(username: str, password_hash: str) -> bool:
    return _create_initial_admin(username, password_hash, "developer")


def list_admins() -> list[dict[str, Any]]:
    with closing(_connect()) as connection:
        rows = connection.execute(
            """
            SELECT id, username, role, is_active, created_at
            FROM admin_users
            ORDER BY CASE role WHEN 'developer' THEN 0 WHEN 'owner' THEN 1 ELSE 2 END,
                     username ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def create_admin(username: str, password_hash: str, role: str) -> int:
    with closing(_connect()) as connection:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO admin_users (
                    username, password_hash, role, is_active, created_at
                ) VALUES (?, ?, ?, 1, ?)
                """,
                (username, password_hash, role, _utc_now()),
            )
            return int(cursor.lastrowid)


def update_admin(
    admin_id: int, *, password_hash: str | None, role: str, is_active: bool
) -> None:
    with closing(_connect()) as connection:
        with connection:
            if password_hash:
                connection.execute(
                    """
                    UPDATE admin_users
                    SET password_hash = ?, role = ?, is_active = ?
                    WHERE id = ?
                    """,
                    (password_hash, role, int(is_active), admin_id),
                )
            else:
                connection.execute(
                    "UPDATE admin_users SET role = ?, is_active = ? WHERE id = ?",
                    (role, int(is_active), admin_id),
                )
