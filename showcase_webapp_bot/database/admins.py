"""Учётные записи админки и журнал их действий."""

from contextlib import closing
from typing import Any

from database.connection import connect, utc_now


def log_action(
    admin_id: int | None, username: str, action: str, target: str = "", details: str = ""
) -> None:
    with closing(connect()) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO admin_actions (
                    admin_id, username, action, target, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (admin_id, username, action, target, details, utc_now()),
            )


def list_actions(limit: int = 100) -> list[dict[str, Any]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM admin_actions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def delete_admin(admin_id: int) -> bool:
    with closing(connect()) as connection:
        with connection:
            cursor = connection.execute(
                "DELETE FROM admin_users WHERE id = ?", (admin_id,)
            )
            return cursor.rowcount > 0


def get_admin_by_username(username: str) -> dict[str, Any] | None:
    with closing(connect()) as connection:
        row = connection.execute(
            """
            SELECT id, username, password_hash, role, is_active
            FROM admin_users WHERE username = ?
            """,
            (username,),
        ).fetchone()
    return dict(row) if row else None


def get_admin(admin_id: int) -> dict[str, Any] | None:
    with closing(connect()) as connection:
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
    with closing(connect()) as connection:
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
                (username, password_hash, role, utc_now()),
            )
        return True


def create_initial_owner(username: str, password_hash: str) -> bool:
    return _create_initial_admin(username, password_hash, "owner")


def create_initial_developer(username: str, password_hash: str) -> bool:
    return _create_initial_admin(username, password_hash, "developer")


def list_admins() -> list[dict[str, Any]]:
    with closing(connect()) as connection:
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
    with closing(connect()) as connection:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO admin_users (
                    username, password_hash, role, is_active, created_at
                ) VALUES (?, ?, ?, 1, ?)
                """,
                (username, password_hash, role, utc_now()),
            )
            return int(cursor.lastrowid)


def update_admin(
    admin_id: int, *, password_hash: str | None, role: str, is_active: bool
) -> None:
    with closing(connect()) as connection:
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
