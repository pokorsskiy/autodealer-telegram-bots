"""Сводка для первого экрана админки."""

from contextlib import closing

from database.connection import connect


def catalog_summary() -> dict[str, int]:
    """Короткая сводка для первого экрана админки."""
    with closing(connect()) as connection:
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
