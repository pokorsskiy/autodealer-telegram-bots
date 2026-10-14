"""Flask-приложение каталога и админки.

Собирается фабрикой create_app: настройки читаются из config в момент вызова,
маршруты разнесены по blueprint-ам.
"""

import secrets

from flask import Flask, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

import config
from database import create_initial_developer, create_initial_owner, init_db
from logger import logger
from webapp import admin_api, admin_pages, demo, public

TEMPLATES_DIR = config.BASE_DIR / "templates"


def _bootstrap() -> None:
    init_db()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if config.ADMIN_USERNAME and config.ADMIN_PASSWORD:
        if len(config.ADMIN_PASSWORD) < 12:
            logger.warning("ADMIN_PASSWORD должен содержать не менее 12 символов")
        else:
            created = create_initial_owner(
                config.ADMIN_USERNAME, generate_password_hash(config.ADMIN_PASSWORD)
            )
            if created:
                logger.info("Создан первоначальный владелец веб-админки")
    if config.DEVELOPER_USERNAME and config.DEVELOPER_PASSWORD:
        if len(config.DEVELOPER_PASSWORD) < 12:
            logger.warning("DEVELOPER_PASSWORD должен содержать не менее 12 символов")
        else:
            created = create_initial_developer(
                config.DEVELOPER_USERNAME, generate_password_hash(config.DEVELOPER_PASSWORD)
            )
            if created:
                logger.info("Создан разработчик веб-админки")


def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        # Всё своё: сторонние адреса (telegram.org, Google Fonts) в России бывают недоступны.
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' https: data: blob:; "
        "connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.path.startswith("/api/") or request.path.startswith("/admin"):
        response.headers["Cache-Control"] = "no-store"
    elif request.path.endswith((".html", ".css", ".js")) or request.path == "/":
        response.headers["Cache-Control"] = "no-cache"
    elif request.path.endswith((".jpg", ".jpeg", ".png", ".webp", ".woff2")):
        # Фото и шрифт не перекачиваются при каждом открытии: на мобильном это заметно.
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response


def upload_too_large(_error):
    return jsonify({"error": f"Файл больше {config.MAX_UPLOAD_MB} МБ"}), 413


def internal_error(_error):
    logger.exception("Внутренняя ошибка Web-сервера")
    return jsonify({"error": "Внутренняя ошибка сервера"}), 500


def create_app() -> Flask:
    if config.DEMO_MODE is None:
        raise RuntimeError("Не задан DEMO_MODE в .env: 1 — демо без заявок, 0 — рабочая витрина.")
    if config.DEMO_MODE is False and config.LEGAL_MISSING:
        logger.warning(
            "legal.json не заполнен (%s): страницы политики и согласия недоступны",
            ", ".join(config.LEGAL_MISSING),
        )
    if not config.SECRET_KEY:
        logger.warning("SECRET_KEY не задан: при перезапуске сервера все сессии админки завершатся")

    app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
    # Сервер стоит за nginx: без этого remote_addr у всех посетителей 127.0.0.1,
    # и ограничения попыток входа и заявок срабатывали бы на всех сразу.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
    app.config.update(
        SECRET_KEY=config.SECRET_KEY or secrets.token_hex(32),
        MAX_CONTENT_LENGTH=config.MAX_UPLOAD_MB * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
    )
    for module in (public, demo, admin_pages, admin_api):
        app.register_blueprint(module.bp)
    app.after_request(security_headers)
    app.register_error_handler(413, upload_too_large)
    app.register_error_handler(500, internal_error)
    _bootstrap()
    return app
