"""Web-сервер публичного каталога и закрытой админки."""

import csv
import hashlib
import hmac
import io
import json
import re
import secrets
import shutil
import sqlite3
import time
from collections import defaultdict, deque
from collections.abc import Callable
from functools import wraps
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import requests
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from requests.exceptions import RequestException
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from config import (
    ADMIN_EXTRA_BOT_TOKENS,
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    ADMIN_WEB_APP_URL,
    BASE_DIR,
    DEMO_MODE,
    DEVELOPER_PASSWORD,
    DEVELOPER_USERNAME,
    LEAD_NOTIFY_CONTACTS,
    LEGAL,
    LEGAL_MISSING,
    MAX_UPLOAD_MB,
    PUBLIC_LINKS,
    SECRET_KEY,
    SESSION_COOKIE_SECURE,
    SITE_EMAIL,
    SITE_OWNER,
    TELEGRAM_ADMINS,
    TELEGRAM_API_URL,
    TOKEN,
    UPLOAD_DIR,
    WEB_HOST,
    WEB_PORT,
    YOUR_CHAT_ID,
)
from database import (
    LEAD_STATUSES,
    add_car_image,
    catalog_summary,
    create_admin,
    create_initial_developer,
    create_initial_owner,
    delete_admin,
    delete_car,
    delete_car_image,
    delete_lead,
    get_admin,
    get_admin_by_username,
    get_car,
    get_lead,
    init_db,
    list_actions,
    list_admins,
    list_cars,
    list_leads,
    log_action,
    reorder_car_images,
    save_car,
    save_lead,
    set_car_sold,
    set_lead_archived,
    update_admin,
    update_lead,
)
from logger import logger

if DEMO_MODE is None:
    raise RuntimeError("Не задан DEMO_MODE в .env: 1 — демо без заявок, 0 — рабочая витрина.")

WEB_DIR = BASE_DIR / "web"
# Демо под конкретного перегонщика: demos/<имя>/demo.json и фото рядом.
# В Git не хранится — это чужие машины и фото.
DEMOS_DIR = BASE_DIR / "demos"
TEMPLATES_DIR = BASE_DIR / "templates"
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
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
# Заявку от другого бота принимаем, только если она подписана недавно.
BOT_LEAD_MAX_AGE = 300
LEAD_WINDOW_SECONDS = 600
LEAD_MAX_PER_WINDOW = 5
REQUIRED_LEAD_FIELDS = ("name", "phone", "car_interest", "purchase_method", "lead_type")
LEAD_MAX_LENGTHS = {
    "name": 80,
    "phone": 30,
    "username": 64,
    "car_interest": 80,
    "purchase_method": 40,
    "comment": 500,
    "lead_type": 20,
    "car_id": 80,
}
LEAD_TYPES = {"car", "manager"}
# Так форма и другой бот отмечают согласие на обработку персональных данных.
CONSENT_VALUES = {"1", "true", "on"}
# В демо страницы политики и согласия показывают образец с вымышленным оператором.
LEGAL_SAMPLE = {
    "operator": "ООО «АвтоПривоз»",
    "inn": "0000000000",
    "ogrn": "0000000000000",
    "address": "000000, г. Город, ул. Примерная, д. 1",
    "email": "info@example.ru",
    "contact": "@manager",
    "responsible": "директор Иванов И. И.",
    "bot": "@example_bot",
    "processor": "Петров Пётр Петрович",
    "processor_inn": "000000000000",
    "storage": "3 лет",
    "updated": "01.01.2026",
}
login_attempts: dict[str, deque[float]] = defaultdict(deque)
lead_attempts: dict[str, deque[float]] = defaultdict(deque)

app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
app.config.update(
    SECRET_KEY=SECRET_KEY or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
)

if DEMO_MODE is False and LEGAL_MISSING:
    logger.warning(
        "legal.json не заполнен (%s): страницы политики и согласия недоступны",
        ", ".join(LEGAL_MISSING),
    )

if not SECRET_KEY:
    logger.warning(
        "SECRET_KEY не задан: при перезапуске сервера все сессии админки завершатся"
    )


def _bootstrap() -> None:
    init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if ADMIN_USERNAME and ADMIN_PASSWORD:
        if len(ADMIN_PASSWORD) < 12:
            logger.warning("ADMIN_PASSWORD должен содержать не менее 12 символов")
        else:
            created = create_initial_owner(
                ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD)
            )
            if created:
                logger.info("Создан первоначальный владелец веб-админки")
    if DEVELOPER_USERNAME and DEVELOPER_PASSWORD:
        if len(DEVELOPER_PASSWORD) < 12:
            logger.warning("DEVELOPER_PASSWORD должен содержать не менее 12 символов")
        else:
            created = create_initial_developer(
                DEVELOPER_USERNAME, generate_password_hash(DEVELOPER_PASSWORD)
            )
            if created:
                logger.info("Создан разработчик веб-админки")


def _owner_setup_error() -> str:
    admins = list_admins()
    if any(user["role"] == "owner" and user["is_active"] for user in admins):
        return ""
    if not ADMIN_USERNAME:
        return "Владелец не создан: задайте ADMIN_USERNAME в локальном .env."
    if len(ADMIN_PASSWORD) < 12:
        return (
            "Владелец не создан: ADMIN_PASSWORD должен содержать "
            "не менее 12 символов. После изменения перезапустите сервер."
        )
    return "Владелец не создан. Проверьте журнал запуска и перезапустите сервер."


def _csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return str(token)


def _require_csrf() -> None:
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    expected = session.get("csrf_token")
    if not supplied or not expected or not hmac.compare_digest(str(supplied), str(expected)):
        abort(403)


def _current_admin() -> dict[str, Any] | None:
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
            admin = _current_admin()
            if admin is None:
                if request.path.startswith("/api/admin/"):
                    return jsonify({"error": "Требуется авторизация"}), 401
                return redirect(url_for("admin_login"))
            if ROLE_LEVEL[admin["role"]] < ROLE_LEVEL[role]:
                return jsonify({"error": "Недостаточно прав"}), 403
            return handler(*args, **kwargs)

        return wrapper

    return decorator


def _log(action: str, target: str = "", details: str = "") -> None:
    """Запись в журнал: когда менеджеров несколько, важно знать, кто менял."""
    admin = _current_admin()
    if admin is None:
        return
    log_action(int(admin["id"]), str(admin["username"]), action, target, details)


def _json_object() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400)
    return payload


def _clean_text(
    payload: dict[str, Any], name: str, *, max_length: int, required: bool = True
) -> str:
    value = str(payload.get(name, "")).strip()
    if required and not value:
        raise ValueError(f"Поле «{name}» обязательно")
    if len(value) > max_length:
        raise ValueError(f"Поле «{name}» слишком длинное")
    return value


def _clean_int(
    payload: dict[str, Any], name: str, *, minimum: int, maximum: int
) -> int:
    try:
        value = int(payload.get(name))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Поле «{name}» должно быть числом") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"Некорректное значение поля «{name}»")
    return value


def _validate_car(payload: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    car_id = _clean_text(payload, "id", max_length=80) if creating else ""
    if creating and not SLUG_RE.fullmatch(car_id):
        raise ValueError("ID: только латиница, цифры и дефисы")
    location = _clean_text(payload, "location", max_length=10)
    if location not in {"city", "port"}:
        raise ValueError("Некорректный статус автомобиля")
    return {
        "id": car_id,
        "brand": _clean_text(payload, "brand", max_length=60),
        "model": _clean_text(payload, "model", max_length=80),
        "year": _clean_int(payload, "year", minimum=1950, maximum=2100),
        "price": _clean_int(payload, "price", minimum=0, maximum=1_000_000_000),
        "mileage": _clean_int(payload, "mileage", minimum=0, maximum=10_000_000),
        "body": _clean_text(payload, "body", max_length=60),
        "drive": _clean_text(payload, "drive", max_length=60),
        "engine": _clean_text(payload, "engine", max_length=100),
        "power": _clean_text(payload, "power", max_length=60),
        "description": _clean_text(
            payload, "description", max_length=2000, required=False
        ),
        "location": location,
        "is_visible": bool(payload.get("is_visible", True)),
        "sort_order": _clean_int(
            {"sort_order": payload.get("sort_order", 0)},
            "sort_order",
            minimum=-10000,
            maximum=10000,
        ),
    }


def _remove_local_upload(url: str | None) -> None:
    if not url or not url.startswith("/uploads/"):
        return
    filename = Path(url).name
    target = (UPLOAD_DIR / filename).resolve()
    if target.parent == UPLOAD_DIR.resolve() and target.exists():
        target.unlink()


def _login_is_limited(client_key: str) -> bool:
    now = time.monotonic()
    attempts = login_attempts[client_key]
    while attempts and now - attempts[0] > LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def _record_failed_login(client_key: str) -> None:
    login_attempts[client_key].append(time.monotonic())


def _telegram_user(init_data: str, max_age: int) -> dict[str, Any] | None:
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
    for token in filter(None, [TOKEN, *ADMIN_EXTRA_BOT_TOKENS]):
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        for variant in variants:
            check_string = "\n".join(f"{k}={v}" for k, v in sorted(variant.items()))
            expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, received_hash):
                return user
    return None


def _telegram_user_id(init_data: str) -> int | None:
    user = _telegram_user(init_data, TELEGRAM_LOGIN_MAX_AGE)
    return user["id"] if user else None


def _lead_is_limited(client_key: str) -> bool:
    """Форма заявки открыта всем, поэтому ограничиваем поток с одного адреса."""
    now = time.monotonic()
    attempts = lead_attempts[client_key]
    while attempts and now - attempts[0] > LEAD_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= LEAD_MAX_PER_WINDOW


def _has_consent(payload: dict[str, Any]) -> bool:
    """Без согласия на обработку персональных данных заявку не принимаем."""
    return str(payload.get("consent", "")).strip().lower() in CONSENT_VALUES


def _validate_lead(payload: dict[str, Any]) -> dict[str, str] | None:
    """Те же правила, что и у заявки из Telegram: расходиться им незачем."""
    if not _has_consent(payload):
        return None
    lead = {
        field: str(payload.get(field, "")).strip() for field in LEAD_MAX_LENGTHS
    }
    if any(not lead[field] for field in REQUIRED_LEAD_FIELDS):
        return None
    if any(len(lead[field]) > limit for field, limit in LEAD_MAX_LENGTHS.items()):
        return None
    if lead["lead_type"] not in LEAD_TYPES:
        return None
    if len(lead["name"]) < 2 or len(re.sub(r"\D", "", lead["phone"])) < 10:
        return None
    if lead["lead_type"] == "manager" and len(lead["comment"]) < 3:
        return None
    return lead


def _notify_lead(
    lead_id: int, lead: dict[str, str], telegram_user: dict[str, Any] | None = None
) -> bool:
    """Отправляет заявку владельцу напрямую через Bot API.

    Кроме основного бота заявка уходит в чаты ботов из ADMIN_EXTRA_BOT_TOKENS
    (гибрид): они показывают ту же витрину, и владелец ждёт заявку и там.
    """
    if not TOKEN or not YOUR_CHAT_ID:
        logger.warning("Заявка не отправлена: не задан токен бота или чат владельца")
        return False

    label = "Заявка на автомобиль" if lead["lead_type"] == "car" else "Помощь с выбором"
    if not LEAD_NOTIFY_CONTACTS:
        return _send_lead_notice(lead_id, _short_lead_text(label, lead_id, lead))
    if telegram_user:
        full_name = " ".join(
            filter(None, [telegram_user.get("first_name"), telegram_user.get("last_name")])
        ) or lead["name"]
        username = telegram_user.get("username")
        source = (
            f'<a href="tg://user?id={telegram_user["id"]}">{escape(full_name)}</a>'
            + (f" (@{escape(username)})" if username else "")
            + f", Telegram <code>{telegram_user['id']}</code>"
        )
    else:
        source = "витрина в браузере"
    text = (
        f"🔥 <b>{label} №{lead_id}</b>\n\n"
        f"📍 <b>Источник:</b> {source}\n"
        f"✍️ <b>Имя:</b> {escape(lead['name'])}\n"
        f"📞 <b>Телефон:</b> <code>{escape(lead['phone'])}</code>\n"
        f"💬 <b>Username:</b> {escape(lead['username']) or '—'}\n"
        f"🚗 <b>Автомобиль:</b> {escape(lead['car_interest'])}\n"
        f"💳 <b>Покупка:</b> {escape(lead['purchase_method'])}\n"
        f"📝 <b>Комментарий:</b> {escape(lead['comment']) or '—'}"
    )
    return _send_lead_notice(lead_id, text)


def _short_lead_text(label: str, lead_id: int, lead: dict[str, str]) -> str:
    """Уведомление без персональных данных: контакты клиента — только в админке."""
    return (
        f"🔥 <b>{label} №{lead_id}</b>\n\n"
        f"🚗 <b>Автомобиль:</b> {escape(lead['car_interest'])}\n"
        f"💳 <b>Покупка:</b> {escape(lead['purchase_method'])}\n\n"
        "Контакты клиента — в админке."
    )


def _admin_button() -> dict[str, Any] | None:
    """Кнопка админки под уведомлением. Web App-кнопки Telegram разрешает
    только в личном чате, в группе админка открывается ссылкой."""
    if not ADMIN_WEB_APP_URL:
        return None
    if YOUR_CHAT_ID and YOUR_CHAT_ID > 0:
        return {"text": "🔐 Открыть админку", "web_app": {"url": ADMIN_WEB_APP_URL}}
    return {"text": "🔐 Открыть админку", "url": ADMIN_WEB_APP_URL.removesuffix("/tg")}


def _send_lead_notice(lead_id: int, text: str) -> bool:
    take = [{"text": "Взял в работу", "callback_data": f"lead:take:{lead_id}"}]
    admin = _admin_button()
    delivered = False
    for token in [TOKEN, *ADMIN_EXTRA_BOT_TOKENS]:
        message = {"chat_id": YOUR_CHAT_ID, "text": text, "parse_mode": "HTML"}
        # «Взял в работу» обрабатывает только основной бот.
        rows = [take] if token == TOKEN else []
        if admin and not LEAD_NOTIFY_CONTACTS:
            rows.append([admin])
        if rows:
            message["reply_markup"] = {"inline_keyboard": rows}
        try:
            response = requests.post(
                f"{TELEGRAM_API_URL}/bot{token}/sendMessage",
                json=message,
                timeout=10,
            )
        except RequestException:
            # Без текста ошибки: в нём бывает полный URL вместе с токеном.
            logger.exception("Не удалось связаться с Telegram для заявки №%s", lead_id)
            continue
        if response.status_code != 200:
            logger.warning(
                "Telegram отклонил уведомление о заявке №%s: код %s",
                lead_id,
                response.status_code,
            )
            continue
        delivered = True
    return delivered


def _valid_image_signature(image) -> bool:
    header = image.stream.read(16)
    image.stream.seek(0)
    return (
        header.startswith(b"\xff\xd8\xff")
        or header.startswith(b"\x89PNG\r\n\x1a\n")
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    )


@app.after_request
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


@app.get("/")
def webapp_index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/check")
def phone_check():
    """Проверка телефона для тех, у кого не открывается каталог."""
    return send_from_directory(WEB_DIR, "check.html")


def _legal_page(template: str):
    """Политика и согласие: в демо — образец, у заказчика — его реквизиты."""
    if DEMO_MODE:
        details = LEGAL_SAMPLE
    elif LEGAL_MISSING:
        abort(404)
    else:
        details = LEGAL
    return render_template(
        template, legal=details, sample=bool(DEMO_MODE), site=request.host_url.rstrip("/")
    )


@app.get("/privacy")
def privacy_policy():
    return _legal_page("privacy.html")


@app.get("/consent")
def personal_data_consent():
    return _legal_page("consent.html")


@app.get("/<path:filename>")
def webapp_asset(filename: str):
    if filename.startswith(("admin", "api/", "uploads/")):
        abort(404)
    return send_from_directory(WEB_DIR, filename)


@app.get("/uploads/<path:filename>")
def uploaded_image(filename: str):
    return send_from_directory(UPLOAD_DIR, filename)


@app.get("/api/cars")
def public_cars():
    return jsonify({"cars": list_cars(include_hidden=False)})


@app.get("/api/links")
def public_links():
    """Отдаёт витрине только заполненные адреса: пустые кнопки не рисуются."""
    return jsonify({name: url for name, url in PUBLIC_LINKS.items() if url})


@app.get("/api/demos/<slug>")
def public_demo(slug: str):
    """Название, цвет и машины демо для ссылки ?demo=<имя>. Только в демо-режиме.

    Хозяину песочницы вместо исходных машин отдаются его машины из демо-админки.
    После срока демо отвечает 410 с названием — витрина показывает «демо завершено».
    """
    demo = _demo_config(slug) if DEMO_MODE else None
    if demo is None:
        abort(404)
    if _demo_expired(demo):
        return jsonify({"expired": True, "brand": demo.get("brand", "")}), 410
    identity, _cookie = _sandbox_identity(create=False)
    cars = _sandbox_cars(slug, identity)
    if cars is not None:
        demo = {**demo, "cars": cars, "sandbox": True}
    return jsonify(demo)


@app.get("/demos/<slug>/<path:filename>")
def demo_image(slug: str, filename: str):
    if not DEMO_MODE or not SLUG_RE.match(slug):
        abort(404)
    return send_from_directory(DEMOS_DIR / slug, filename)


# --- Песочница демо-админки -------------------------------------------------
# Что перегонщик поменял в демо-админке, видно в его демо-каталоге: и в Telegram
# (два мини-приложения), и в браузере. Чтобы демо не стало бесплатным рабочим
# каталогом, песочницу видит только её хозяин (Telegram-аккаунт или cookie
# браузера), а по ссылке остальные видят исходное демо; у демо есть срок
# (expires в demo.json), песочница живёт неделю, заявки по-прежнему не принимаются.
DEMO_SANDBOX_DIR = BASE_DIR / "demo_sandboxes"
DEMO_SANDBOX_COOKIE = "demo_sb"
DEMO_SANDBOX_TTL = 7 * 86400
DEMO_SANDBOX_MAX_CARS = 60
DEMO_SANDBOX_MAX_PHOTOS = 40
DEMO_SANDBOX_MAX_PHOTO_BYTES = 3 * 1024 * 1024
DEMO_SANDBOX_WRITES_PER_MINUTE = 60
DEMO_CAR_TEXT_LIMITS = {
    "id": 80, "brand": 60, "model": 80, "body": 40, "drive": 40, "engine": 80,
    "power": 40, "location": 10, "description": 2000, "created_at": 40, "sold_at": 40,
}
demo_sandbox_writes: dict[str, deque[float]] = defaultdict(deque)


def _demo_config(slug: str) -> dict[str, Any] | None:
    path = DEMOS_DIR / slug / "demo.json"
    if not SLUG_RE.fullmatch(slug) or not path.is_file():
        return None
    try:
        demo = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("Не удалось прочитать демо %s", slug)
        return None
    return demo if isinstance(demo, dict) else None


def _demo_expired(demo: dict[str, Any]) -> bool:
    """expires — последний день демо, «2026-10-19»; без него демо бессрочное."""
    expires = str(demo.get("expires", "")).strip()
    return bool(expires) and time.strftime("%Y-%m-%d", time.gmtime()) > expires


def _sandbox_identity(create: bool) -> tuple[str | None, str | None]:
    """Хозяин песочницы: аккаунт Telegram, иначе cookie браузера.

    Возвращает (личность, новая cookie): cookie выдаётся только при записи.
    """
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        user = _telegram_user(init_data, TELEGRAM_LEAD_MAX_AGE)
        if user:
            return f"tg:{user['id']}", None
    cookie = request.cookies.get(DEMO_SANDBOX_COOKIE, "")
    if re.fullmatch(r"[0-9a-f]{32}", cookie):
        return f"web:{cookie}", None
    if not create:
        return None, None
    cookie = secrets.token_hex(16)
    return f"web:{cookie}", cookie


def _sandbox_dir(slug: str, identity: str) -> Path:
    secret = app.config["SECRET_KEY"].encode()
    key = hmac.new(secret, f"{slug}:{identity}".encode(), hashlib.sha256).hexdigest()[:32]
    return DEMO_SANDBOX_DIR / slug / key


def _sandbox_cars(slug: str, identity: str | None) -> list[dict[str, Any]] | None:
    if not identity:
        return None
    path = _sandbox_dir(slug, identity) / "cars.json"
    if not path.is_file() or time.time() - path.stat().st_mtime > DEMO_SANDBOX_TTL:
        return None
    try:
        cars = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cars if isinstance(cars, list) else None


def _purge_old_sandboxes() -> None:
    """Песочницы, которые не трогали неделю, и песочницы закончившихся демо удаляются."""
    if not DEMO_SANDBOX_DIR.is_dir():
        return
    now = time.time()
    for slug_dir in DEMO_SANDBOX_DIR.iterdir():
        demo = _demo_config(slug_dir.name)
        expired = demo is None or _demo_expired(demo)
        for box in slug_dir.iterdir() if slug_dir.is_dir() else []:
            if expired or now - box.stat().st_mtime > DEMO_SANDBOX_TTL:
                shutil.rmtree(box, ignore_errors=True)


def _clean_sandbox_car(raw: Any, slug: str, box_url: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    car: dict[str, Any] = {}
    for name, limit in DEMO_CAR_TEXT_LIMITS.items():
        value = raw.get(name)
        car[name] = "" if value is None else str(value)[:limit]
    if not SLUG_RE.fullmatch(car["id"]) or car["location"] not in {"city", "port"}:
        return None
    for name in ("year", "price", "mileage", "sort_order"):
        try:
            car[name] = max(0, min(int(raw.get(name) or 0), 10**9))
        except (TypeError, ValueError):
            car[name] = 0
    car["is_visible"] = bool(raw.get("is_visible", True))
    car["is_sold"] = bool(raw.get("is_sold", False))
    images = []
    for image in raw.get("images") or []:
        url = str(image.get("url", "")) if isinstance(image, dict) else ""
        # Только фото самого демо и фото, загруженные в эту же песочницу.
        if re.fullmatch(rf"/demos/{slug}/[\w.-]+", url) or re.fullmatch(
            rf"{re.escape(box_url)}/[0-9a-f]{{16}}\.(jpg|png|webp)", url
        ):
            images.append({
                "url": url, "alt_text": str(image.get("alt_text", ""))[:120],
                "sort_order": len(images),
            })
    car["images"] = images[:12]
    return car


def _sandbox_write_allowed(identity: str) -> bool:
    now = time.monotonic()
    writes = demo_sandbox_writes[identity]
    while writes and now - writes[0] > 60:
        writes.popleft()
    if len(writes) >= DEMO_SANDBOX_WRITES_PER_MINUTE:
        return False
    writes.append(now)
    return True


def _with_sandbox_cookie(response: Response, cookie: str | None) -> Response:
    if cookie:
        response.set_cookie(
            DEMO_SANDBOX_COOKIE, cookie, max_age=DEMO_SANDBOX_TTL, httponly=True,
            samesite="Lax", secure=SESSION_COOKIE_SECURE,
        )
    return response


def _open_demo_for_sandbox(slug: str) -> dict[str, Any]:
    demo = _demo_config(slug) if DEMO_MODE else None
    if demo is None:
        abort(404)
    if _demo_expired(demo):
        abort(410)
    return demo


@app.put("/api/demos/<slug>/sandbox")
def demo_sandbox_save(slug: str):
    _open_demo_for_sandbox(slug)
    identity, cookie = _sandbox_identity(create=True)
    if not _sandbox_write_allowed(identity):
        return jsonify({"error": "Слишком много изменений подряд. Подождите минуту."}), 429
    payload = _json_object()
    raw_cars = payload.get("cars")
    if not isinstance(raw_cars, list) or len(raw_cars) > DEMO_SANDBOX_MAX_CARS:
        return jsonify({"error": f"В демо можно держать до {DEMO_SANDBOX_MAX_CARS} автомобилей"}), 400
    box = _sandbox_dir(slug, identity)
    box_url = f"/demo-sandbox/{slug}/{box.name}"
    cars = [car for car in (_clean_sandbox_car(raw, slug, box_url) for raw in raw_cars) if car]
    box.mkdir(parents=True, exist_ok=True)
    (box / "cars.json").write_text(json.dumps(cars, ensure_ascii=False), encoding="utf-8")
    _purge_old_sandboxes()
    return _with_sandbox_cookie(jsonify({"ok": True, "cars": len(cars)}), cookie)


@app.delete("/api/demos/<slug>/sandbox")
def demo_sandbox_reset(slug: str):
    _open_demo_for_sandbox(slug)
    identity, _cookie = _sandbox_identity(create=False)
    if identity:
        shutil.rmtree(_sandbox_dir(slug, identity), ignore_errors=True)
    return jsonify({"ok": True})


@app.post("/api/demos/<slug>/sandbox/photos")
def demo_sandbox_photos(slug: str):
    _open_demo_for_sandbox(slug)
    identity, cookie = _sandbox_identity(create=True)
    if not _sandbox_write_allowed(identity):
        return jsonify({"error": "Слишком много изменений подряд. Подождите минуту."}), 429
    box = _sandbox_dir(slug, identity)
    existing = len([p for p in box.glob("*") if p.name != "cars.json"]) if box.is_dir() else 0
    images = [file for file in request.files.getlist("image") if file and file.filename]
    if not images:
        return jsonify({"error": "Выберите изображение"}), 400
    if existing + len(images) > DEMO_SANDBOX_MAX_PHOTOS:
        return jsonify({"error": f"В демо можно загрузить до {DEMO_SANDBOX_MAX_PHOTOS} фото"}), 400
    box.mkdir(parents=True, exist_ok=True)
    urls = []
    for image in images:
        extension = image.filename.rsplit(".", 1)[-1].lower()
        extension = "jpg" if extension == "jpeg" else extension
        data = image.read(DEMO_SANDBOX_MAX_PHOTO_BYTES + 1)
        image.stream.seek(0)
        if (
            extension not in ALLOWED_IMAGE_EXTENSIONS
            or len(data) > DEMO_SANDBOX_MAX_PHOTO_BYTES
            or not _valid_image_signature(image)
        ):
            return jsonify({"error": f"«{image.filename}» — не JPG, PNG или WEBP до 3 МБ"}), 400
        filename = f"{secrets.token_hex(8)}.{extension}"
        (box / filename).write_bytes(data)
        urls.append(f"/demo-sandbox/{slug}/{box.name}/{filename}")
    return _with_sandbox_cookie(jsonify({"urls": urls}), cookie), 201


@app.get("/demo-sandbox/<slug>/<key>/<filename>")
def demo_sandbox_image(slug: str, key: str, filename: str):
    demo = _demo_config(slug) if DEMO_MODE else None
    if (
        demo is None or _demo_expired(demo) or not re.fullmatch(r"[0-9a-f]{32}", key)
        or not re.fullmatch(r"[0-9a-f]{16}\.(jpg|png|webp)", filename)
    ):
        abort(404)
    return send_from_directory(DEMO_SANDBOX_DIR / slug / key, filename)


@app.get("/api/site")
def public_site():
    """Режим витрины и сведения о владельце для подвала."""
    return jsonify({"demo": DEMO_MODE, "owner": SITE_OWNER, "email": SITE_EMAIL})


@app.post("/api/leads")
def public_lead():
    """Заявка из витрины: и из браузера, и из Telegram.

    Внутри Telegram витрина прикладывает подписанные данные запуска: по ним
    видно, кто оставил заявку. Telegram.WebApp.sendData тут не подходит — он
    работает только у Web App, открытых кнопкой клавиатуры, а у ботов кнопки
    inline.
    """
    if DEMO_MODE:
        # Витрина в демо заявку не отправляет; это страховка от старой версии
        # страницы в кэше и прямых запросов.
        return jsonify({"error": "Это демо: заявки не принимаются."}), 403
    client_key = request.remote_addr or "unknown"
    if _lead_is_limited(client_key):
        return jsonify({"error": "Слишком много заявок. Попробуйте позже."}), 429

    payload = _json_object()
    if not _has_consent(payload):
        return jsonify({"error": "Отметьте согласие на обработку персональных данных."}), 400
    lead = _validate_lead(payload)
    if lead is None:
        return jsonify({"error": "Проверьте имя, телефон и остальные поля."}), 400

    init_data = str(payload.get("init_data") or "")
    telegram_user = _telegram_user(init_data, TELEGRAM_LEAD_MAX_AGE) if init_data else None
    if telegram_user:
        lead_id = save_lead(telegram_user["id"], telegram_user.get("username"), lead)
    else:
        lead_id = save_lead(0, None, lead, source="site")
    lead_attempts[client_key].append(time.monotonic())
    delivered = _notify_lead(lead_id, lead, telegram_user)
    if not delivered:
        logger.warning("Заявка №%s сохранена, но не отправлена в Telegram", lead_id)
    return jsonify({"ok": True, "lead_id": lead_id, "delivered": delivered})


@app.post("/api/bot/leads")
def bot_lead():
    """Заявка из Web App, открытого в другом боте (гибрид).

    Уведомление в Telegram тот бот отправляет сам, а сюда передаёт заявку,
    чтобы её вели в админке вместе с остальными. Запрос подписан токеном бота
    из ADMIN_EXTRA_BOT_TOKENS: HMAC-SHA256 от тела в заголовке X-Bot-Signature.
    """
    if DEMO_MODE:
        return jsonify({"error": "Это демо: заявки не принимаются."}), 403
    body = request.get_data()
    signature = request.headers.get("X-Bot-Signature", "")
    if not any(
        hmac.compare_digest(
            hmac.new(token.encode(), body, hashlib.sha256).hexdigest(), signature
        )
        for token in ADMIN_EXTRA_BOT_TOKENS
    ):
        return jsonify({"error": "Неверная подпись"}), 403

    payload = _json_object()
    try:
        sent_at = int(payload.get("sent_at", 0))
        user_id = int(payload.get("user_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректная заявка"}), 400
    if abs(time.time() - sent_at) > BOT_LEAD_MAX_AGE:
        return jsonify({"error": "Устаревший запрос"}), 403
    raw_lead = payload.get("lead")
    lead = _validate_lead(raw_lead) if isinstance(raw_lead, dict) else None
    if lead is None:
        return jsonify({"error": "Некорректная заявка"}), 400

    username = str(payload.get("username") or "")[:64] or None
    lead_id = save_lead(user_id, username, lead)
    return jsonify({"ok": True, "lead_id": lead_id})


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if _current_admin():
        return redirect(url_for("admin_panel"))
    error = ""
    if request.method == "POST":
        _require_csrf()
        client_key = request.remote_addr or "unknown"
        if _login_is_limited(client_key):
            return render_template(
                "login.html",
                csrf_token=_csrf_token(),
                error="Слишком много попыток. Попробуйте через 5 минут.",
                setup_error=_owner_setup_error(),
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
            return redirect(url_for("admin_panel"))
        _record_failed_login(client_key)
        error = "Неверный логин или пароль"
    return render_template(
        "login.html",
        csrf_token=_csrf_token(),
        error=error,
        setup_error=_owner_setup_error(),
    )


@app.get("/admin/tg")
def admin_telegram_entry():
    """Страница, которую открывает кнопка /admin в боте."""
    if _current_admin():
        return redirect(url_for("admin_panel"))
    return render_template("telegram_login.html", csrf_token=_csrf_token())


@app.post("/admin/tg")
def admin_telegram_login():
    """Вход без пароля для Telegram-аккаунтов из ADMIN_TELEGRAM_IDS."""
    _require_csrf()
    client_key = request.remote_addr or "unknown"
    if _login_is_limited(client_key):
        return jsonify({"error": "Слишком много попыток. Попробуйте через 5 минут."}), 429

    init_data = str(_json_object().get("init_data", ""))
    telegram_id = _telegram_user_id(init_data)
    username = TELEGRAM_ADMINS.get(telegram_id) if telegram_id else None
    admin = get_admin_by_username(username) if username else None
    if not admin or not admin["is_active"]:
        _record_failed_login(client_key)
        logger.warning("Отказ во входе в админку из Telegram, ID %s", telegram_id)
        return jsonify({"error": "Для этого Telegram-аккаунта вход без пароля не открыт."}), 403

    session.clear()
    session["admin_id"] = int(admin["id"])
    session["csrf_token"] = secrets.token_urlsafe(32)
    login_attempts.pop(client_key, None)
    return jsonify({"ok": True, "redirect": url_for("admin_panel")})


@app.post("/admin/logout")
@login_required()
def admin_logout():
    _require_csrf()
    session.clear()
    return redirect(url_for("admin_login"))


@app.get("/admin")
@login_required()
def admin_panel():
    return render_template(
        "admin.html", admin=_current_admin(), csrf_token=_csrf_token()
    )


@app.get("/admin/demo")
def admin_demo():
    """Админка-песочница для потенциальных клиентов, только в демо-режиме.

    Входа нет и сессия не создаётся: все запросы админки в этом режиме
    обрабатывает admin.js в памяти браузера, а настоящие /api/admin/*
    без входа по-прежнему отвечают 401. Каталог на сервере не меняется.
    """
    if not DEMO_MODE:
        abort(404)
    return render_template(
        "admin.html", admin={"username": "owner", "role": "owner"}, csrf_token="demo", demo=True
    )


@app.get("/admin/<path:filename>")
def admin_asset(filename: str):
    return send_from_directory(WEB_DIR / "admin", filename)


@app.get("/api/admin/leads")
@login_required()
def admin_leads():
    return jsonify({"leads": list_leads()})


@app.patch("/api/admin/leads/<int:lead_id>")
@login_required()
def admin_update_lead(lead_id: int):
    _require_csrf()
    payload = _json_object()
    lead = get_lead(lead_id)
    if lead is None:
        return jsonify({"error": "Заявка не найдена"}), 404
    status = str(payload.get("status", lead["status"]))
    note = str(payload.get("note", lead["note"])).strip()
    if status not in LEAD_STATUSES:
        return jsonify({"error": "Некорректный статус"}), 400
    if len(note) > 1000:
        return jsonify({"error": "Заметка длиннее 1000 символов"}), 400
    admin = _current_admin()
    handled_by = str(admin["username"]) if status != "new" else lead["handled_by"]
    update_lead(lead_id, status=status, note=note, handled_by=handled_by)
    _log("Обновил заявку", f"№{lead_id}", status)
    return "", 204


@app.post("/api/admin/leads/<int:lead_id>/archive")
@login_required()
def admin_archive_lead(lead_id: int):
    """Архив убирает заявку из рабочего списка, вернуть её можно в любой момент."""
    _require_csrf()
    archived = bool(_json_object().get("archived", True))
    if not set_lead_archived(lead_id, archived):
        return jsonify({"error": "Заявка не найдена"}), 404
    _log("Убрал заявку в архив" if archived else "Вернул заявку из архива", f"№{lead_id}")
    return "", 204


@app.delete("/api/admin/leads/<int:lead_id>")
@login_required("owner")
def admin_delete_lead(lead_id: int):
    """Удаление навсегда — только владельцу: менеджер убирает заявки в архив."""
    _require_csrf()
    if not delete_lead(lead_id):
        return jsonify({"error": "Заявка не найдена"}), 404
    _log("Удалил заявку", f"№{lead_id}")
    return "", 204


@app.get("/api/admin/leads.csv")
@login_required()
def admin_leads_csv():
    """Выгрузка для тех, кто ведёт клиентов в таблице, а не в админке."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "Номер", "Дата", "Источник", "Статус", "Имя", "Телефон",
            "Контакт", "Тип", "Автомобиль", "Покупка", "Комментарий", "Заметка",
            "В архиве", "Согласие на обработку ПД",
        ]
    )
    for lead in list_leads(limit=5000):
        writer.writerow(
            [
                lead["id"], lead["created_at"], lead["source"], lead["status"],
                lead["name"], lead["phone"],
                lead["contact_username"] or lead["username"] or "",
                lead["lead_type"], lead["car_interest"], lead["purchase_method"],
                lead["comment"] or "", lead["note"],
                "да" if lead["is_archived"] else "",
                lead["consent_at"],
            ]
        )
    _log("Выгрузил заявки")
    # BOM: без него Excel открывает кириллицу в CSV как набор символов.
    data = "﻿" + buffer.getvalue()
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@app.get("/api/admin/summary")
@login_required()
def admin_summary():
    return jsonify(catalog_summary())


@app.get("/api/admin/actions")
@login_required("owner")
def admin_actions():
    return jsonify({"actions": list_actions()})


@app.post("/api/admin/cars/<car_id>/sold")
@login_required()
def admin_mark_sold(car_id: str):
    _require_csrf()
    payload = _json_object()
    sold = bool(payload.get("sold", True))
    if not set_car_sold(car_id, sold):
        return jsonify({"error": "Автомобиль не найден"}), 404
    _log("Отметил продажу" if sold else "Вернул в продажу", car_id)
    return "", 204


@app.get("/api/admin/session")
@login_required()
def admin_session():
    admin = _current_admin()
    return jsonify(
        {
            "user": {
                "id": admin["id"],
                "username": admin["username"],
                "role": admin["role"],
            },
            "csrf_token": _csrf_token(),
        }
    )


@app.get("/api/admin/cars")
@login_required()
def admin_cars():
    return jsonify({"cars": list_cars(include_hidden=True)})


@app.post("/api/admin/cars")
@login_required()
def admin_create_car():
    _require_csrf()
    try:
        car = _validate_car(_json_object(), creating=True)
        save_car(car)
    except (ValueError, sqlite3.IntegrityError) as error:
        return jsonify({"error": str(error)}), 400
    _log("Создал карточку", car["id"], f"{car['brand']} {car['model']}")
    return jsonify({"car": get_car(car["id"])}), 201


@app.put("/api/admin/cars/<car_id>")
@login_required()
def admin_update_car(car_id: str):
    _require_csrf()
    if get_car(car_id) is None:
        return jsonify({"error": "Автомобиль не найден"}), 404
    try:
        car = _validate_car(_json_object(), creating=False)
        save_car(car, original_id=car_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    _log("Изменил карточку", car_id, f"{car['brand']} {car['model']}")
    return jsonify({"car": get_car(car_id)})


@app.delete("/api/admin/cars/<car_id>")
@login_required("owner")
def admin_delete_car(car_id: str):
    _require_csrf()
    if get_car(car_id) is None:
        return jsonify({"error": "Автомобиль не найден"}), 404
    local_urls = delete_car(car_id)
    for url in local_urls:
        _remove_local_upload(url)
    _log("Удалил карточку", car_id)
    return "", 204


@app.post("/api/admin/cars/<car_id>/images")
@login_required()
def admin_upload_image(car_id: str):
    _require_csrf()
    car = get_car(car_id)
    if car is None:
        return jsonify({"error": "Автомобиль не найден"}), 404
    images = [file for file in request.files.getlist("image") if file and file.filename]
    if not images:
        return jsonify({"error": "Выберите изображение"}), 400

    saved = []
    for image in images:
        extension = image.filename.rsplit(".", 1)[-1].lower()
        if (
            extension not in ALLOWED_IMAGE_EXTENSIONS
            or not image.mimetype.startswith("image/")
            or not _valid_image_signature(image)
        ):
            return jsonify(
                {"error": f"«{image.filename}» не является корректным JPG, PNG или WEBP"}
            ), 400
        safe_stem = secure_filename(Path(image.filename).stem)[:40] or "car"
        filename = f"{safe_stem}-{secrets.token_hex(8)}.{extension}"
        image.save(UPLOAD_DIR / filename)
        image_id = add_car_image(
            car_id, f"/uploads/{filename}", f"{car['brand']} {car['model']}"
        )
        saved.append({"image_id": image_id, "url": f"/uploads/{filename}"})

    _log("Загрузил фотографии", car_id, f"{len(saved)} шт.")
    return jsonify({"images": saved, **saved[0]}), 201


@app.delete("/api/admin/images/<int:image_id>")
@login_required()
def admin_delete_image(image_id: int):
    _require_csrf()
    url = delete_car_image(image_id)
    if url is None:
        return jsonify({"error": "Фотография не найдена"}), 404
    _remove_local_upload(url)
    return "", 204


@app.put("/api/admin/cars/<car_id>/images/order")
@login_required()
def admin_reorder_images(car_id: str):
    _require_csrf()
    payload = _json_object()
    try:
        image_ids = [int(value) for value in payload.get("image_ids", [])]
        reorder_car_images(car_id, image_ids)
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректный порядок фотографий"}), 400
    return "", 204


def _can_manage(role: str) -> bool:
    return role in MANAGEABLE_ROLES[_current_admin()["role"]]


@app.get("/api/admin/users")
@login_required("owner")
def admin_users():
    current = _current_admin()
    users = [
        {**user, "can_manage": _can_manage(user["role"]) and user["id"] != current["id"]}
        for user in list_admins()
    ]
    return jsonify(
        {"users": users, "assignable_roles": sorted(MANAGEABLE_ROLES[current["role"]], key=ROLE_LEVEL.get)}
    )


@app.post("/api/admin/users")
@login_required("owner")
def admin_create_user():
    _require_csrf()
    payload = _json_object()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", "manager"))
    if not USERNAME_RE.fullmatch(username):
        return jsonify({"error": "Некорректный логин"}), 400
    if len(password) < 12:
        return jsonify({"error": "Пароль должен содержать не менее 12 символов"}), 400
    if role not in ROLE_LEVEL:
        return jsonify({"error": "Некорректная роль"}), 400
    if not _can_manage(role):
        return jsonify({"error": "Недостаточно прав для этой роли"}), 403
    try:
        admin_id = create_admin(username, generate_password_hash(password), role)
    except sqlite3.IntegrityError:
        return jsonify({"error": "Такой логин уже существует"}), 400
    _log("Создал учётную запись", username, role)
    return jsonify({"id": admin_id}), 201


@app.put("/api/admin/users/<int:admin_id>")
@login_required("owner")
def admin_update_user(admin_id: int):
    _require_csrf()
    current = _current_admin()
    target = get_admin(admin_id)
    if target is None:
        return jsonify({"error": "Пользователь не найден"}), 404
    payload = _json_object()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", target["role"]))
    is_active = bool(payload.get("is_active", target["is_active"]))
    if role not in ROLE_LEVEL:
        return jsonify({"error": "Некорректная роль"}), 400
    if not (_can_manage(target["role"]) and _can_manage(role)):
        return jsonify({"error": "Недостаточно прав для этой учётной записи"}), 403
    if password and len(password) < 12:
        return jsonify({"error": "Пароль должен содержать не менее 12 символов"}), 400
    if admin_id == current["id"] and (not is_active or role != current["role"]):
        return jsonify({"error": "Нельзя лишить себя собственного доступа"}), 400
    update_admin(
        admin_id,
        password_hash=generate_password_hash(password) if password else None,
        role=role,
        is_active=is_active,
    )
    _log("Изменил учётную запись", str(target["username"]), role)
    return "", 204


@app.delete("/api/admin/users/<int:admin_id>")
@login_required("owner")
def admin_delete_user(admin_id: int):
    _require_csrf()
    current = _current_admin()
    if admin_id == current["id"]:
        return jsonify({"error": "Нельзя удалить собственную учётную запись"}), 400
    target = get_admin(admin_id)
    if target is None:
        return jsonify({"error": "Пользователь не найден"}), 404
    if not _can_manage(target["role"]):
        return jsonify({"error": "Недостаточно прав для этой учётной записи"}), 403
    delete_admin(admin_id)
    _log("Удалил учётную запись", str(target["username"]))
    return "", 204


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({"error": f"Файл больше {MAX_UPLOAD_MB} МБ"}), 413


@app.errorhandler(500)
def internal_error(_error):
    logger.exception("Внутренняя ошибка Web-сервера")
    return jsonify({"error": "Внутренняя ошибка сервера"}), 500


_bootstrap()


if __name__ == "__main__":
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)
