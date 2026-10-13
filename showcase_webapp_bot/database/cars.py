"""Каталог автомобилей и фотографии."""

import sqlite3
from contextlib import closing
from typing import Any

from database.connection import connect, utc_now

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


def set_car_sold(car_id: str, sold: bool) -> bool:
    """Проданная машина уходит из витрины, но остаётся в админке."""
    with closing(connect()) as connection:
        with connection:
            cursor = connection.execute(
                """
                UPDATE catalog_cars
                SET is_sold = ?, sold_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(sold), utc_now() if sold else "", utc_now(), car_id),
            )
            return cursor.rowcount > 0


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
    with closing(connect()) as connection:
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
    with closing(connect()) as connection:
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
    now = utc_now()
    with closing(connect()) as connection:
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
    with closing(connect()) as connection:
        with connection:
            connection.execute("DELETE FROM catalog_cars WHERE id = ?", (car_id,))
    return local_urls


def add_car_image(car_id: str, url: str, alt_text: str = "") -> int:
    with closing(connect()) as connection:
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
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT url FROM car_images WHERE id = ?", (image_id,)
        ).fetchone()
        if row is None:
            return None
        with connection:
            connection.execute("DELETE FROM car_images WHERE id = ?", (image_id,))
        return str(row["url"])


def reorder_car_images(car_id: str, image_ids: list[int]) -> None:
    with closing(connect()) as connection:
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
