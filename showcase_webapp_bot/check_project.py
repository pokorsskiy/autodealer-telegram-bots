"""Быстрая диагностика Web App showcase."""

import ast
import sys
from pathlib import Path

from config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    DEMO_MODE,
    LEGAL_MISSING,
    SECRET_KEY,
    SITE_EMAIL,
    SITE_OWNER,
    TELEGRAM_API_URL,
    WEB_APP_URL,
)

# В консоли Windows с кодировкой cp1251 эмодзи в выводе роняли скрипт
# UnicodeEncodeError: недостающие символы заменяются, кириллица остаётся.
sys.stdout.reconfigure(errors="replace")


BASE_DIR = Path(__file__).resolve().parent
PYTHON_FILES = [
    BASE_DIR / "bot.py",
    BASE_DIR / "config.py",
    BASE_DIR / "database.py",
    BASE_DIR / "keyboards.py",
    BASE_DIR / "logger.py",
    BASE_DIR / "server.py",
]
WEB_FILES = [
    BASE_DIR / "web" / "index.html",
    BASE_DIR / "web" / "style.css",
    BASE_DIR / "web" / "app.js",
    BASE_DIR / "web" / "admin" / "admin.css",
    BASE_DIR / "web" / "admin" / "admin.js",
    BASE_DIR / "templates" / "login.html",
    BASE_DIR / "templates" / "admin.html",
]
ASSET_FILES = [BASE_DIR / "menu-cover.jpg"]


def main() -> int:
    missing = [
        path.name
        for path in [*PYTHON_FILES, *WEB_FILES, *ASSET_FILES]
        if not path.exists()
    ]
    if missing:
        print(f"❌ Нет файлов: {', '.join(missing)}")
        return 1
    print("🔍 Файлы: OK")

    for path in PYTHON_FILES:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print("🔍 Python-синтаксис: OK")

    html = WEB_FILES[0].read_text(encoding="utf-8")
    javascript = WEB_FILES[2].read_text(encoding="utf-8")
    admin_html = WEB_FILES[6].read_text(encoding="utf-8")
    admin_js = WEB_FILES[4].read_text(encoding="utf-8")
    required_html = (
        'id="catalog"',
        'id="lead-form"',
        # Без согласия на обработку персональных данных форма незаконна.
        'name="consent"',
        'id="car-dialog"',
        'id="favorites-dialog"',
        'data-location-jump="city"',
        'data-view="grid"',
        "telegram-web-app.js",
    )
    required_js = (
        'fetch("/api/cars"',
        "telegram.sendData",
        # Избранное и просмотренные переживают закрытие приложения.
        "localStorage",
        'fetch("/api/leads"',
        "calculateDutyEur",
        "openLead",
        "renderFavorites",
        "renderCompare",
    )
    required_admin = (
        'id="car-form"',
        'id="photo-upload"',
        "/api/admin/cars",
        "/api/admin/leads",
        "X-CSRF-Token",
    )
    if not all(marker in html for marker in required_html):
        print("❌ HTML: отсутствуют обязательные разделы")
        return 1
    if not all(marker in javascript for marker in required_js):
        print("❌ JavaScript: отсутствуют обязательные сценарии")
        return 1
    if "favoritesOnly" in javascript:
        print("❌ JavaScript: избранное не должно менять фильтры каталога")
        return 1
    if not all(marker in f"{admin_html}\n{admin_js}" for marker in required_admin):
        print("❌ Админка: отсутствуют обязательные сценарии")
        return 1
    print("🔍 Web App и админка: OK")

    if DEMO_MODE is None:
        print("❌ DEMO_MODE не задан: 1 — демо без заявок, 0 — рабочая витрина")
        return 1
    print("🔍 Режим:", "демо, заявки не принимаются" if DEMO_MODE else "рабочий")
    if DEMO_MODE is False and LEGAL_MISSING:
        print(
            "❌ legal.json: рабочей витрине нужны реквизиты оператора для политики "
            "и согласия, не заполнено: " + ", ".join(LEGAL_MISSING)
        )
        return 1
    print("🔍 Политика и согласие: " + ("образец для демо" if DEMO_MODE else "реквизиты заполнены"))
    print(
        "🔍 Telegram API: "
        + ("напрямую" if TELEGRAM_API_URL == "https://api.telegram.org" else "через посредника")
    )
    print(
        "🔍 Владелец сайта в подвале: "
        + ("настроен" if SITE_OWNER and SITE_EMAIL else "нужно настроить SITE_OWNER и SITE_EMAIL")
    )

    print(f"🔍 HTTPS URL: {'настроен' if WEB_APP_URL.startswith('https://') else 'нужно настроить'}")
    print(
        "🔍 Владелец: "
        + ("настроен" if ADMIN_USERNAME and len(ADMIN_PASSWORD) >= 12 else "нужно настроить")
    )
    print(
        "🔍 SECRET_KEY: "
        + ("настроен" if len(SECRET_KEY) >= 32 else "нужно настроить")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
