"""SQLite-хранилище заявок, каталога и пользователей веб-админки.

Снаружи пакет используется как один модуль: from database import save_lead.
"""

from database.admins import (
    create_admin,
    create_initial_developer,
    create_initial_owner,
    delete_admin,
    get_admin,
    get_admin_by_username,
    list_actions,
    list_admins,
    log_action,
    update_admin,
)
from database.cars import (
    add_car_image,
    delete_car,
    delete_car_image,
    get_car,
    list_cars,
    reorder_car_images,
    save_car,
    set_car_sold,
)
from database.leads import (
    LEAD_STATUSES,
    delete_lead,
    get_lead,
    list_leads,
    save_lead,
    set_lead_archived,
    update_lead,
)
from database.schema import init_db
from database.seed import DEMO_IMAGE_MOVES
from database.stats import catalog_summary

__all__ = [
    "DEMO_IMAGE_MOVES",
    "LEAD_STATUSES",
    "add_car_image",
    "catalog_summary",
    "create_admin",
    "create_initial_developer",
    "create_initial_owner",
    "delete_admin",
    "delete_car",
    "delete_car_image",
    "delete_lead",
    "get_admin",
    "get_admin_by_username",
    "get_car",
    "get_lead",
    "init_db",
    "list_actions",
    "list_admins",
    "list_cars",
    "list_leads",
    "log_action",
    "reorder_car_images",
    "save_car",
    "save_lead",
    "set_car_sold",
    "set_lead_archived",
    "update_admin",
    "update_lead",
]
