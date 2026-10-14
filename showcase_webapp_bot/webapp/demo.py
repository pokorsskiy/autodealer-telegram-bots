"""Именные демо и песочница демо-админки. Работают только в демо-режиме."""

import hashlib
import hmac
import json
import re
import secrets
import shutil
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, abort, current_app, jsonify, request, send_from_directory

import config
from logger import logger
from webapp.auth import TELEGRAM_LEAD_MAX_AGE, verify_init_data
from webapp.validation import ALLOWED_IMAGE_EXTENSIONS, SLUG_RE, json_object, valid_image_signature

bp = Blueprint("demo", __name__)


# Демо под конкретного перегонщика: demos/<имя>/demo.json и фото рядом.
# В Git не хранится — это чужие машины и фото.
DEMOS_DIR = config.BASE_DIR / "demos"


@bp.get("/api/demos/<slug>")
def public_demo(slug: str):
    """Название, цвет и машины демо для ссылки ?demo=<имя>. Только в демо-режиме.

    Хозяину песочницы вместо исходных машин отдаются его машины из демо-админки.
    После срока демо отвечает 410 с названием — витрина показывает «демо завершено».
    """
    demo = _demo_config(slug) if config.DEMO_MODE else None
    if demo is None:
        abort(404)
    if _demo_expired(demo):
        return jsonify({"expired": True, "brand": demo.get("brand", "")}), 410
    identity, _cookie = _sandbox_identity(create=False)
    cars = _sandbox_cars(slug, identity)
    if cars is not None:
        demo = {**demo, "cars": cars, "sandbox": True}
    return jsonify(demo)


@bp.get("/demos/<slug>/<path:filename>")
def demo_image(slug: str, filename: str):
    if not config.DEMO_MODE or not SLUG_RE.match(slug):
        abort(404)
    return send_from_directory(DEMOS_DIR / slug, filename)


# --- Песочница демо-админки -------------------------------------------------
# Что перегонщик поменял в демо-админке, видно в его демо-каталоге: и в Telegram
# (два мини-приложения), и в браузере. Чтобы демо не стало бесплатным рабочим
# каталогом, песочницу видит только её хозяин (Telegram-аккаунт или cookie
# браузера), а по ссылке остальные видят исходное демо; у демо есть срок
# (expires в demo.json), песочница живёт неделю, заявки по-прежнему не принимаются.
DEMO_SANDBOX_DIR = config.BASE_DIR / "demo_sandboxes"
DEMO_SANDBOX_COOKIE = "demo_sb"
DEMO_SANDBOX_TTL = 7 * 86400
DEMO_SANDBOX_MAX_CARS = 60
DEMO_SANDBOX_MAX_PHOTOS = 40
DEMO_SANDBOX_MAX_PHOTO_BYTES = 3 * 1024 * 1024
DEMO_SANDBOX_WRITES_PER_MINUTE = 60
# Запрос без cookie получает новую песочницу, поэтому новые песочницы считаются
# по адресу посетителя, а все фото вместе ограничены, чтобы демо не заняло диск.
DEMO_SANDBOX_NEW_PER_HOUR = 10
DEMO_SANDBOX_MAX_TOTAL_BYTES = 500 * 1024 * 1024
DEMO_CAR_TEXT_LIMITS = {
    "id": 80, "brand": 60, "model": 80, "body": 40, "drive": 40, "engine": 80,
    "power": 40, "location": 10, "description": 2000, "created_at": 40, "sold_at": 40,
}
demo_sandbox_writes: dict[str, deque[float]] = defaultdict(deque)
demo_sandbox_created: dict[str, deque[float]] = defaultdict(deque)


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
        user = verify_init_data(init_data, TELEGRAM_LEAD_MAX_AGE)
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
    secret = current_app.config["SECRET_KEY"].encode()
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


def _within_limit(attempts: deque[float], window: int, limit: int) -> bool:
    now = time.monotonic()
    while attempts and now - attempts[0] > window:
        attempts.popleft()
    if len(attempts) >= limit:
        return False
    attempts.append(now)
    return True


def _sandbox_write_allowed(identity: str, new_cookie: str | None) -> bool:
    client_key = request.remote_addr or "unknown"
    if new_cookie and not _within_limit(
        demo_sandbox_created[client_key], 3600, DEMO_SANDBOX_NEW_PER_HOUR
    ):
        return False
    return _within_limit(demo_sandbox_writes[identity], 60, DEMO_SANDBOX_WRITES_PER_MINUTE)


def _sandboxes_size() -> int:
    if not DEMO_SANDBOX_DIR.is_dir():
        return 0
    return sum(path.stat().st_size for path in DEMO_SANDBOX_DIR.rglob("*") if path.is_file())


def _with_sandbox_cookie(response: Response, cookie: str | None) -> Response:
    if cookie:
        response.set_cookie(
            DEMO_SANDBOX_COOKIE, cookie, max_age=DEMO_SANDBOX_TTL, httponly=True,
            samesite="Lax", secure=config.SESSION_COOKIE_SECURE,
        )
    return response


def _open_demo_for_sandbox(slug: str) -> dict[str, Any]:
    demo = _demo_config(slug) if config.DEMO_MODE else None
    if demo is None:
        abort(404)
    if _demo_expired(demo):
        abort(410)
    return demo


@bp.put("/api/demos/<slug>/sandbox")
def demo_sandbox_save(slug: str):
    _open_demo_for_sandbox(slug)
    identity, cookie = _sandbox_identity(create=True)
    if not _sandbox_write_allowed(identity, cookie):
        return jsonify({"error": "Слишком много изменений подряд. Попробуйте позже."}), 429
    payload = json_object()
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


@bp.delete("/api/demos/<slug>/sandbox")
def demo_sandbox_reset(slug: str):
    _open_demo_for_sandbox(slug)
    identity, _cookie = _sandbox_identity(create=False)
    if identity:
        shutil.rmtree(_sandbox_dir(slug, identity), ignore_errors=True)
    return jsonify({"ok": True})


@bp.post("/api/demos/<slug>/sandbox/photos")
def demo_sandbox_photos(slug: str):
    _open_demo_for_sandbox(slug)
    identity, cookie = _sandbox_identity(create=True)
    if not _sandbox_write_allowed(identity, cookie):
        return jsonify({"error": "Слишком много изменений подряд. Попробуйте позже."}), 429
    _purge_old_sandboxes()
    if _sandboxes_size() + (request.content_length or 0) > DEMO_SANDBOX_MAX_TOTAL_BYTES:
        logger.warning("Место под фото демо-песочниц закончилось")
        return jsonify({"error": "Место для фото в демо временно закончилось. Попробуйте позже."}), 503
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
            or not valid_image_signature(image)
        ):
            return jsonify({"error": f"«{image.filename}» — не JPG, PNG или WEBP до 3 МБ"}), 400
        filename = f"{secrets.token_hex(8)}.{extension}"
        (box / filename).write_bytes(data)
        urls.append(f"/demo-sandbox/{slug}/{box.name}/{filename}")
    return _with_sandbox_cookie(jsonify({"urls": urls}), cookie), 201


@bp.get("/demo-sandbox/<slug>/<key>/<filename>")
def demo_sandbox_image(slug: str, key: str, filename: str):
    demo = _demo_config(slug) if config.DEMO_MODE else None
    if (
        demo is None or _demo_expired(demo) or not re.fullmatch(r"[0-9a-f]{32}", key)
        or not re.fullmatch(r"[0-9a-f]{16}\.(jpg|png|webp)", filename)
    ):
        abort(404)
    return send_from_directory(DEMO_SANDBOX_DIR / slug / key, filename)
