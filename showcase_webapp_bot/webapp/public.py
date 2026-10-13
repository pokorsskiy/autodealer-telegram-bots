"""Публичная часть: каталог, страницы политики и согласия, приём заявок."""

import hashlib
import hmac
import time
from collections import defaultdict, deque

from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory

import config
from database import list_cars, save_lead
from logger import logger
from webapp.auth import TELEGRAM_LEAD_MAX_AGE, verify_init_data
from webapp.notifications import notify_lead
from webapp.validation import has_consent, json_object, validate_lead

bp = Blueprint("public", __name__)


WEB_DIR = config.BASE_DIR / "web"


# Заявку от другого бота принимаем, только если она подписана недавно.
BOT_LEAD_MAX_AGE = 300
LEAD_WINDOW_SECONDS = 600
LEAD_MAX_PER_WINDOW = 5


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


lead_attempts: dict[str, deque[float]] = defaultdict(deque)


def _lead_is_limited(client_key: str) -> bool:
    """Форма заявки открыта всем, поэтому ограничиваем поток с одного адреса."""
    now = time.monotonic()
    attempts = lead_attempts[client_key]
    while attempts and now - attempts[0] > LEAD_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= LEAD_MAX_PER_WINDOW


@bp.get("/")
def webapp_index():
    return send_from_directory(WEB_DIR, "index.html")


@bp.get("/check")
def phone_check():
    """Проверка телефона для тех, у кого не открывается каталог."""
    return send_from_directory(WEB_DIR, "check.html")


def _legal_page(template: str):
    """Политика и согласие: в демо — образец, у заказчика — его реквизиты."""
    if config.DEMO_MODE:
        details = LEGAL_SAMPLE
    elif config.LEGAL_MISSING:
        abort(404)
    else:
        details = config.LEGAL
    return render_template(
        template, legal=details, sample=bool(config.DEMO_MODE), site=request.host_url.rstrip("/")
    )


@bp.get("/privacy")
def privacy_policy():
    return _legal_page("privacy.html")


@bp.get("/consent")
def personal_data_consent():
    return _legal_page("consent.html")


@bp.get("/<path:filename>")
def webapp_asset(filename: str):
    if filename.startswith(("admin", "api/", "uploads/")):
        abort(404)
    return send_from_directory(WEB_DIR, filename)


@bp.get("/uploads/<path:filename>")
def uploaded_image(filename: str):
    return send_from_directory(config.UPLOAD_DIR, filename)


@bp.get("/api/cars")
def public_cars():
    return jsonify({"cars": list_cars(include_hidden=False)})


@bp.get("/api/links")
def public_links():
    """Отдаёт витрине только заполненные адреса: пустые кнопки не рисуются."""
    return jsonify({name: url for name, url in config.PUBLIC_LINKS.items() if url})


@bp.get("/api/site")
def public_site():
    """Режим витрины и сведения о владельце для подвала."""
    return jsonify({"demo": config.DEMO_MODE, "owner": config.SITE_OWNER, "email": config.SITE_EMAIL})


@bp.post("/api/leads")
def public_lead():
    """Заявка из витрины: и из браузера, и из Telegram.

    Внутри Telegram витрина прикладывает подписанные данные запуска: по ним
    видно, кто оставил заявку. Telegram.WebApp.sendData тут не подходит — он
    работает только у Web App, открытых кнопкой клавиатуры, а у ботов кнопки
    inline.
    """
    if config.DEMO_MODE:
        # Витрина в демо заявку не отправляет; это страховка от старой версии
        # страницы в кэше и прямых запросов.
        return jsonify({"error": "Это демо: заявки не принимаются."}), 403
    client_key = request.remote_addr or "unknown"
    if _lead_is_limited(client_key):
        return jsonify({"error": "Слишком много заявок. Попробуйте позже."}), 429

    payload = json_object()
    if not has_consent(payload):
        return jsonify({"error": "Отметьте согласие на обработку персональных данных."}), 400
    lead = validate_lead(payload)
    if lead is None:
        return jsonify({"error": "Проверьте имя, телефон и остальные поля."}), 400

    init_data = str(payload.get("init_data") or "")
    telegram_user = verify_init_data(init_data, TELEGRAM_LEAD_MAX_AGE) if init_data else None
    if telegram_user:
        lead_id = save_lead(telegram_user["id"], telegram_user.get("username"), lead)
    else:
        lead_id = save_lead(0, None, lead, source="site")
    lead_attempts[client_key].append(time.monotonic())
    delivered = notify_lead(lead_id, lead, telegram_user)
    if not delivered:
        logger.warning("Заявка №%s сохранена, но не отправлена в Telegram", lead_id)
    return jsonify({"ok": True, "lead_id": lead_id, "delivered": delivered})


@bp.post("/api/bot/leads")
def bot_lead():
    """Заявка из Web App, открытого в другом боте (гибрид).

    Уведомление в Telegram тот бот отправляет сам, а сюда передаёт заявку,
    чтобы её вели в админке вместе с остальными. Запрос подписан токеном бота
    из ADMIN_EXTRA_BOT_TOKENS: HMAC-SHA256 от тела в заголовке X-Bot-Signature.
    """
    if config.DEMO_MODE:
        return jsonify({"error": "Это демо: заявки не принимаются."}), 403
    body = request.get_data()
    signature = request.headers.get("X-Bot-Signature", "")
    if not any(
        hmac.compare_digest(
            hmac.new(token.encode(), body, hashlib.sha256).hexdigest(), signature
        )
        for token in config.ADMIN_EXTRA_BOT_TOKENS
    ):
        return jsonify({"error": "Неверная подпись"}), 403

    payload = json_object()
    try:
        sent_at = int(payload.get("sent_at", 0))
        user_id = int(payload.get("user_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректная заявка"}), 400
    if abs(time.time() - sent_at) > BOT_LEAD_MAX_AGE:
        return jsonify({"error": "Устаревший запрос"}), 403
    raw_lead = payload.get("lead")
    lead = validate_lead(raw_lead) if isinstance(raw_lead, dict) else None
    if lead is None:
        return jsonify({"error": "Некорректная заявка"}), 400

    username = str(payload.get("username") or "")[:64] or None
    lead_id = save_lead(user_id, username, lead)
    return jsonify({"ok": True, "lead_id": lead_id})
