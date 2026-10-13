"""Страницы админки: вход по паролю и из Telegram, панель, демо-панель."""

import secrets

from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

import config
from database import get_admin_by_username
from logger import logger
from webapp.auth import (
    current_admin,
    get_csrf_token,
    login_attempts,
    login_is_limited,
    login_required,
    owner_setup_error,
    record_failed_login,
    require_csrf,
    telegram_user_id,
)
from webapp.public import WEB_DIR
from webapp.validation import json_object

bp = Blueprint("admin", __name__)


@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_admin():
        return redirect(url_for("admin.admin_panel"))
    error = ""
    if request.method == "POST":
        require_csrf()
        client_key = request.remote_addr or "unknown"
        if login_is_limited(client_key):
            return render_template(
                "login.html",
                csrf_token=get_csrf_token(),
                error="Слишком много попыток. Попробуйте через 5 минут.",
                setup_error=owner_setup_error(),
            ), 429
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = get_admin_by_username(username)
        if (
            admin
            and admin["is_active"]
            and check_password_hash(admin["password_hash"], password)
        ):
            session.clear()
            session["admin_id"] = int(admin["id"])
            session["csrf_token"] = secrets.token_urlsafe(32)
            login_attempts.pop(client_key, None)
            return redirect(url_for("admin.admin_panel"))
        record_failed_login(client_key)
        error = "Неверный логин или пароль"
    return render_template(
        "login.html",
        csrf_token=get_csrf_token(),
        error=error,
        setup_error=owner_setup_error(),
    )


@bp.get("/admin/tg")
def admin_telegram_entry():
    """Страница, которую открывает кнопка /admin в боте."""
    if current_admin():
        return redirect(url_for("admin.admin_panel"))
    return render_template("telegram_login.html", csrf_token=get_csrf_token())


@bp.post("/admin/tg")
def admin_telegram_login():
    """Вход без пароля для Telegram-аккаунтов из ADMIN_TELEGRAM_IDS."""
    require_csrf()
    client_key = request.remote_addr or "unknown"
    if login_is_limited(client_key):
        return jsonify({"error": "Слишком много попыток. Попробуйте через 5 минут."}), 429

    init_data = str(json_object().get("init_data", ""))
    telegram_id = telegram_user_id(init_data)
    username = config.TELEGRAM_ADMINS.get(telegram_id) if telegram_id else None
    admin = get_admin_by_username(username) if username else None
    if not admin or not admin["is_active"]:
        record_failed_login(client_key)
        logger.warning("Отказ во входе в админку из Telegram, ID %s", telegram_id)
        return jsonify({"error": "Для этого Telegram-аккаунта вход без пароля не открыт."}), 403

    session.clear()
    session["admin_id"] = int(admin["id"])
    session["csrf_token"] = secrets.token_urlsafe(32)
    login_attempts.pop(client_key, None)
    return jsonify({"ok": True, "redirect": url_for("admin.admin_panel")})


@bp.post("/admin/logout")
@login_required()
def admin_logout():
    require_csrf()
    session.clear()
    return redirect(url_for("admin.admin_login"))


@bp.get("/admin")
@login_required()
def admin_panel():
    return render_template(
        "admin.html", admin=current_admin(), csrf_token=get_csrf_token()
    )


@bp.get("/admin/demo")
def admin_demo():
    """Админка-песочница для потенциальных клиентов, только в демо-режиме.

    Входа нет и сессия не создаётся: все запросы админки в этом режиме
    обрабатывает admin.js в памяти браузера, а настоящие /api/admin/*
    без входа по-прежнему отвечают 401. Каталог на сервере не меняется.
    """
    if not config.DEMO_MODE:
        abort(404)
    return render_template(
        "admin.html", admin={"username": "owner", "role": "owner"}, csrf_token="demo", demo=True
    )


@bp.get("/admin/<path:filename>")
def admin_asset(filename: str):
    return send_from_directory(WEB_DIR / "admin", filename)
