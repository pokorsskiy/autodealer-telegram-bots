"""Конфигурация комбинированного showcase-бота."""

import os
from urllib.parse import urlsplit

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return values
    with open(env_path, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
    return values


ENV = _read_env()


def _get_value(name: str, default: str = "") -> str:
    return ENV.get(name) or os.getenv(f"SHOWCASE_HYBRID_{name}") or default


def _https_url(name: str) -> str:
    value = _get_value(name).strip()
    return value if value.startswith("https://") else ""


def _telegram_url(name: str) -> str:
    value = _get_value(name).strip()
    if value.startswith("@"):
        return f"https://t.me/{value[1:]}"
    if value.startswith(("t.me/", "telegram.me/")):
        return f"https://{value}"
    return value if value.startswith("https://") else ""


TOKEN = _get_value("BOT_TOKEN") or os.getenv("BOT_TOKEN")
_admin_id = _get_value("ADMIN_CHAT_ID") or ENV.get("YOUR_CHAT_ID") or os.getenv("YOUR_CHAT_ID")
try:
    YOUR_CHAT_ID = int(_admin_id) if _admin_id else None
except ValueError:
    YOUR_CHAT_ID = None

# С российского сервера api.telegram.org недоступен: там сюда вписывается адрес
# посредника на зарубежном сервере. Пусто — запросы идут в Telegram напрямую.
TELEGRAM_API_URL = (_https_url("TELEGRAM_API_URL") or "https://api.telegram.org").rstrip("/")

WEB_APP_URL = _https_url("WEB_APP_URL")
_web_app_host = urlsplit(WEB_APP_URL).netloc
# Админка общая с Web App-витриной и живёт на том же сервере.
ADMIN_WEB_APP_URL = f"https://{_web_app_host}/admin/tg" if _web_app_host else ""
# Сюда уходят копии заявок из Web App, чтобы их вели в общей админке.
ADMIN_LEADS_URL = f"https://{_web_app_host}/api/bot/leads" if _web_app_host else ""
# Кому /admin присылает кнопку админки. Формат как у сервера витрины:
# 123456789 или 123456789:login, через запятую; здесь нужны только ID.
TELEGRAM_ADMIN_IDS = {
    int(item.split(":", 1)[0])
    for item in _get_value("ADMIN_TELEGRAM_IDS").split(",")
    if item.split(":", 1)[0].strip().isdigit()
}
MANAGER_URL = _telegram_url("MANAGER_URL")
REVIEWS_URL = _telegram_url("REVIEWS_URL")
COMMUNITY_URL = _telegram_url("COMMUNITY_URL")
TELEGRAM_CHANNEL_URL = _telegram_url("TELEGRAM_CHANNEL_URL")
MAX_URL = _https_url("MAX_URL")
VK_URL = _https_url("VK_URL")
YOUTUBE_URL = _https_url("YOUTUBE_URL")
MENU_COVER_FILE_ID = _get_value("MENU_COVER_FILE_ID")
# Обязательная настройка без значения по умолчанию: 1 — демо, заявки никуда
# не уходят; 0 — рабочий бот заказчика. Иначе None, и бот не запускается.
DEMO_MODE = {"1": True, "0": False}.get(_get_value("DEMO_MODE").strip())

# 0 — уведомление о заявке приходит в Telegram без имени, телефона и профиля
# клиента: номер заявки, машина и кнопка в админку. Серверы Telegram за рубежом,
# так данные клиентов не уходят за границу (ст. 12 152-ФЗ). По умолчанию 1 — полная заявка.
LEAD_NOTIFY_CONTACTS = _get_value("LEAD_NOTIFY_CONTACTS", "1").strip() != "0"

DB_NAME = _get_value("DB_NAME", "showcase_hybrid_leads.db")
if not os.path.isabs(DB_NAME):
    DB_NAME = os.path.join(BASE_DIR, DB_NAME)
