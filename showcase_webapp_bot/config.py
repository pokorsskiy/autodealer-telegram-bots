"""Конфигурация Telegram Web App, каталога и закрытой админки."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent


def _local_env() -> dict[str, str]:
    result: dict[str, str] = {}
    path = BASE_DIR / ".env"
    if path.exists():
        with path.open(encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    result[key.strip()] = value.strip().strip("'\"")
    return result


def _value(local_name: str, environment_name: str, default: str = "") -> str:
    return ENV.get(local_name) or os.getenv(environment_name) or default


ENV = _local_env()
TOKEN = _value("BOT_TOKEN", "SHOWCASE_WEBAPP_BOT_TOKEN")
_admin_id = _value("YOUR_CHAT_ID", "SHOWCASE_WEBAPP_ADMIN_CHAT_ID")
try:
    YOUR_CHAT_ID = int(_admin_id) if _admin_id else None
except ValueError:
    YOUR_CHAT_ID = None

# С российского сервера api.telegram.org недоступен: там сюда вписывается адрес
# посредника на зарубежном сервере. Пусто — запросы идут в Telegram напрямую.
TELEGRAM_API_URL = _value(
    "TELEGRAM_API_URL", "SHOWCASE_WEBAPP_TELEGRAM_API_URL", "https://api.telegram.org"
).rstrip("/")
if not TELEGRAM_API_URL.startswith("https://"):
    TELEGRAM_API_URL = "https://api.telegram.org"

WEB_APP_URL = _value("WEB_APP_URL", "SHOWCASE_WEB_APP_URL")
_web_app_parts = urlsplit(WEB_APP_URL)
# Админка живёт на том же сервере, что и витрина.
ADMIN_WEB_APP_URL = (
    f"https://{_web_app_parts.netloc}/admin/tg"
    if _web_app_parts.scheme == "https" and _web_app_parts.netloc
    else ""
)
MENU_COVER_FILE_ID = _value(
    "MENU_COVER_FILE_ID", "SHOWCASE_WEBAPP_MENU_COVER_FILE_ID"
)
DB_NAME = _value(
    "DB_NAME", "SHOWCASE_WEBAPP_DB_NAME", "showcase_webapp_leads.db"
)
if not os.path.isabs(DB_NAME):
    DB_NAME = str(BASE_DIR / DB_NAME)

ADMIN_USERNAME = _value("ADMIN_USERNAME", "SHOWCASE_WEBAPP_ADMIN_USERNAME")
ADMIN_PASSWORD = _value("ADMIN_PASSWORD", "SHOWCASE_WEBAPP_ADMIN_PASSWORD")
DEVELOPER_USERNAME = _value(
    "DEVELOPER_USERNAME", "SHOWCASE_WEBAPP_DEVELOPER_USERNAME"
)
DEVELOPER_PASSWORD = _value(
    "DEVELOPER_PASSWORD", "SHOWCASE_WEBAPP_DEVELOPER_PASSWORD"
)
def _telegram_admins() -> dict[int, str]:
    """Кто входит в админку из Telegram без пароля и под какой учётной записью.

    Формат: ADMIN_TELEGRAM_IDS=123456789:login,987654321:login2.
    """
    result: dict[int, str] = {}
    raw = _value("ADMIN_TELEGRAM_IDS", "SHOWCASE_WEBAPP_ADMIN_TELEGRAM_IDS")
    for item in raw.split(","):
        telegram_id, _, username = item.strip().partition(":")
        if telegram_id.strip().isdigit():
            result[int(telegram_id)] = username.strip()
    return result


TELEGRAM_ADMINS = _telegram_admins()
# Токены других ботов, из которых тоже открывают админку (гибрид): без них
# сервер не сможет проверить подпись Telegram у их Web App.
ADMIN_EXTRA_BOT_TOKENS = [
    token.strip()
    for token in _value(
        "ADMIN_EXTRA_BOT_TOKENS", "SHOWCASE_WEBAPP_ADMIN_EXTRA_BOT_TOKENS"
    ).split(",")
    if token.strip()
]
SECRET_KEY = _value("SECRET_KEY", "SHOWCASE_WEBAPP_SECRET_KEY")
WEB_HOST = _value("WEB_HOST", "SHOWCASE_WEBAPP_HOST", "127.0.0.1")
try:
    WEB_PORT = int(_value("WEB_PORT", "SHOWCASE_WEBAPP_PORT", "8000"))
except ValueError:
    WEB_PORT = 8000

def _link(local_name: str) -> str:
    """Адрес для витрины: пустое значение означает, что кнопки не будет."""
    value = _value(local_name, f"SHOWCASE_WEBAPP_{local_name}")
    if value.startswith("@"):
        return f"https://t.me/{value[1:]}"
    if value.startswith(("t.me/", "telegram.me/")):
        return f"https://{value}"
    return value if value.startswith("https://") else ""


PUBLIC_LINKS = {
    "channel": _link("TELEGRAM_CHANNEL_URL"),
    "reviews": _link("REVIEWS_URL"),
    "community": _link("COMMUNITY_URL"),
    "max": _link("MAX_URL"),
    "vk": _link("VK_URL"),
    "youtube": _link("YOUTUBE_URL"),
}

# Обязательная настройка без значения по умолчанию: 1 — демо, заявки не
# принимаются; 0 — рабочая витрина заказчика. Иначе None, и сервер с ботом
# не запускаются.
DEMO_MODE = {"1": True, "0": False}.get(
    _value("DEMO_MODE", "SHOWCASE_WEBAPP_DEMO_MODE").strip()
)
# 0 — уведомление о заявке приходит в Telegram без имени, телефона и профиля
# клиента: номер заявки, машина и кнопка в админку. Серверы Telegram за рубежом,
# так данные клиентов не уходят за границу (ст. 12 152-ФЗ). По умолчанию 1 — полная заявка.
LEAD_NOTIFY_CONTACTS = _value(
    "LEAD_NOTIFY_CONTACTS", "SHOWCASE_WEBAPP_LEAD_NOTIFY_CONTACTS", "1"
).strip() != "0"
# Кто отвечает за сайт — показывается в подвале витрины.
SITE_OWNER = _value("SITE_OWNER", "SHOWCASE_WEBAPP_SITE_OWNER")
SITE_EMAIL = _value("SITE_EMAIL", "SHOWCASE_WEBAPP_SITE_EMAIL")

# Сведения об операторе персональных данных для страниц /privacy и /consent.
# Лежат в legal.json рядом с .env (образец — legal.example.json); в демо
# страницы показывают образец, рабочей витрине файл обязателен.
LEGAL_FIELDS = (
    "operator", "inn", "ogrn", "address", "email", "contact", "responsible",
    "bot", "processor", "processor_inn", "storage", "updated",
)


def _legal() -> dict[str, str]:
    path = BASE_DIR / "legal.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {field: str(data.get(field) or "").strip() for field in LEGAL_FIELDS}


LEGAL = _legal()
LEGAL_MISSING = [field for field in LEGAL_FIELDS if not LEGAL.get(field)]

UPLOAD_DIR = BASE_DIR / "uploads"
MAX_UPLOAD_MB = 8
SESSION_COOKIE_SECURE = _value(
    "SESSION_COOKIE_SECURE", "SHOWCASE_WEBAPP_COOKIE_SECURE", "1"
).lower() not in {"0", "false", "no"}
