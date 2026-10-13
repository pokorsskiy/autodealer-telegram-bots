"""Заявки покупателей."""

from contextlib import closing
from typing import Any

from database.connection import connect, utc_now

LEAD_STATUSES = ("new", "in_work", "won", "lost")


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
    now = utc_now()
    with closing(connect()) as connection:
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
    with closing(connect()) as connection:
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
    with closing(connect()) as connection:
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
    with closing(connect()) as connection:
        with connection:
            cursor = connection.execute(
                "UPDATE webapp_leads SET is_archived = ? WHERE id = ?",
                (int(archived), lead_id),
            )
            return cursor.rowcount > 0


def delete_lead(lead_id: int) -> bool:
    with closing(connect()) as connection:
        with connection:
            cursor = connection.execute(
                "DELETE FROM webapp_leads WHERE id = ?", (lead_id,)
            )
            return cursor.rowcount > 0


def get_lead(lead_id: int) -> dict[str, Any] | None:
    with closing(connect()) as connection:
        row = connection.execute(
            "SELECT * FROM webapp_leads WHERE id = ?", (lead_id,)
        ).fetchone()
    return {field: row[field] for field in LEAD_FIELDS} if row else None
