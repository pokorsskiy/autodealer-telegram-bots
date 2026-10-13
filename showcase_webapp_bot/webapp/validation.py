"""Проверка входных данных: карточка автомобиля, заявка, загружаемое фото."""

import re
from typing import Any

from flask import abort, request

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")


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


def json_object() -> dict[str, Any]:
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


def validate_car(payload: dict[str, Any], *, creating: bool) -> dict[str, Any]:
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


def has_consent(payload: dict[str, Any]) -> bool:
    """Без согласия на обработку персональных данных заявку не принимаем."""
    return str(payload.get("consent", "")).strip().lower() in CONSENT_VALUES


def validate_lead(payload: dict[str, Any]) -> dict[str, str] | None:
    """Те же правила, что и у заявки из Telegram: расходиться им незачем."""
    if not has_consent(payload):
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


def valid_image_signature(image) -> bool:
    header = image.stream.read(16)
    image.stream.seek(0)
    return (
        header.startswith(b"\xff\xd8\xff")
        or header.startswith(b"\x89PNG\r\n\x1a\n")
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    )
