"""Вход в админку: сессия, роли, CSRF, проверка подписи Telegram."""

import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Callable
from functools import wraps
from typing import Any
from urllib.parse import parse_qsl

from flask import abort, jsonify, redirect, request, session, url_for

import config
from database import get_admin, list_admins, log_action

ROLE_LEVEL = {"manager": 1, "owner": 2, "developer": 3}
# Кем может распоряжаться роль: владелец заводит своих менеджеров,
# владельцами и разработчиком распоряжается только разработчик.
MANAGEABLE_ROLES = {
    "manager": set(),
    "owner": {"manager"},
    "developer": {"manager", "owner", "developer"},
}
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_ATTEMPTS = 5
# Данные Web App подписаны в момент открытия; старше часа не принимаем.
TELEGRAM_LOGIN_MAX_AGE = 3600
# Витрину листают подолгу, а подпись у заявки нужна только, чтобы показать
# профиль клиента, поэтому здесь срок длиннее.
TELEGRAM_LEAD_MAX_AGE = 86400


login_attempts: dict[str, deque[float]] = defaultdict(deque)


def owner_setup_error() -> str:
    admins = list_admins()
    if any(user["role"] == "owner" and user["is_active"] for user in admins):
        return ""
    if not config.ADMIN_USERNAME:
        return "Владелец не создан: задайте ADMIN_USERNAME в локальном .env."
    if len(config.ADMIN_PASSWORD) < 12:
        return (
            "Владелец не создан: ADMIN_PASSWORD должен содержать "
            "не менее 12 символов. После изменения перезапустите сервер."
        )
    return "Владелец не создан. Проверьте журнал запуска и перезапустите сервер."


def get_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return str(token)


def require_csrf() -> None:
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    expected = session.get("csrf_token")
    if not supplied or not expected or not hmac.compare_digest(str(supplied), str(expected)):
        abort(403)


def current_admin() -> dict[str, Any] | None:
    admin_id = session.get("admin_id")
    if not isinstance(admin_id, int):
        return None
    admin = get_admin(admin_id)
    if not admin or not admin["is_active"]:
        session.clear()
        return None
    return admin


def login_required(role: str = "manager") -> Callable:
    def decorator(handler: Callable) -> Callable:
        @wraps(handler)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            admin = current_admin()
            if admin is None:
                if request.path.startswith("/api/admin/"):
                    return jsonify({"error": "Требуется авторизация"}), 401
                return redirect(url_for("admin.admin_login"))
            if ROLE_LEVEL[admin["role"]] < ROLE_LEVEL[role]:
                return jsonify({"error": "Недостаточно прав"}), 403
            return handler(*args, **kwargs)

        return wrapper

    return decorator


def log_admin_action(action: str, target: str = "", details: str = "") -> None:
    """Запись в журнал: когда менеджеров несколько, важно знать, кто менял."""
    admin = current_admin()
    if admin is None:
        return
    log_action(int(admin["id"]), str(admin["username"]), action, target, details)


def login_is_limited(client_key: str) -> bool:
    now = time.monotonic()
    attempts = login_attempts[client_key]
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def record_failed_login(client_key: str) -> None:
    login_attempts[client_key].append(time.monotonic())


def verify_init_data(init_data: str, max_age: int) -> dict[str, Any] | None:
    """Проверяет подпись Telegram у данных Web App и возвращает пользователя.

    Telegram подписывает данные ключом бота, из которого открыт Web App,
    поэтому подделать их без токена нельзя.
    """
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        received_hash = fields.pop("hash")
        auth_date = int(fields["auth_date"])
        user = json.loads(fields["user"])
        user["id"] = int(user["id"])
    except (ValueError, KeyError, TypeError):
        return None
    if not -60 <= time.time() - auth_date <= max_age:
        return None

    # Поле signature Telegram добавил позже: сверяем подпись и с ним, и без него.
    variants = [fields]
    if "signature" in fields:
        variants.append({k: v for k, v in fields.items() if k != "signature"})
    for token in filter(None, [config.TOKEN, *config.ADMIN_EXTRA_BOT_TOKENS]):
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        for variant in variants:
            check_string = "\n".join(f"{k}={v}" for k, v in sorted(variant.items()))
            expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, received_hash):
                return user
    return None


def telegram_user_id(init_data: str) -> int | None:
    user = verify_init_data(init_data, TELEGRAM_LOGIN_MAX_AGE)
    return user["id"] if user else None


def can_manage(role: str) -> bool:
    return role in MANAGEABLE_ROLES[current_admin()["role"]]
