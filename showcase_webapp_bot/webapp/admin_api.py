"""API админки: заявки, автомобили и фото, сотрудники, журнал."""

import csv
import io
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request, session
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

import config
from database import (
    LEAD_STATUSES,
    add_car_image,
    catalog_summary,
    create_admin,
    delete_admin,
    delete_car,
    delete_car_image,
    delete_lead,
    get_admin,
    get_car,
    get_lead,
    list_actions,
    list_admins,
    list_cars,
    list_leads,
    reorder_car_images,
    save_car,
    set_car_sold,
    set_lead_archived,
    update_admin,
    update_lead,
)
from webapp.auth import (
    MANAGEABLE_ROLES,
    ROLE_LEVEL,
    can_manage,
    current_admin,
    get_csrf_token,
    log_admin_action,
    login_required,
    password_tag,
    require_csrf,
)
from webapp.validation import (
    ALLOWED_IMAGE_EXTENSIONS,
    USERNAME_RE,
    json_object,
    valid_image_signature,
    validate_car,
)

bp = Blueprint("admin_api", __name__)

# Ячейку с такого символа Excel считает формулой: имя «=HYPERLINK(...)» из формы
# заявки сработало бы у менеджера. Апостроф делает ячейку текстом.
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def _remove_local_upload(url: str | None) -> None:
    if not url or not url.startswith("/uploads/"):
        return
    filename = Path(url).name
    target = (config.UPLOAD_DIR / filename).resolve()
    if target.parent == config.UPLOAD_DIR.resolve() and target.exists():
        target.unlink()


@bp.get("/api/admin/leads")
@login_required()
def admin_leads():
    return jsonify({"leads": list_leads()})


@bp.patch("/api/admin/leads/<int:lead_id>")
@login_required()
def admin_update_lead(lead_id: int):
    require_csrf()
    payload = json_object()
    lead = get_lead(lead_id)
    if lead is None:
        return jsonify({"error": "Заявка не найдена"}), 404
    status = str(payload.get("status", lead["status"]))
    note = str(payload.get("note", lead["note"])).strip()
    if status not in LEAD_STATUSES:
        return jsonify({"error": "Некорректный статус"}), 400
    if len(note) > 1000:
        return jsonify({"error": "Заметка длиннее 1000 символов"}), 400
    admin = current_admin()
    handled_by = str(admin["username"]) if status != "new" else lead["handled_by"]
    update_lead(lead_id, status=status, note=note, handled_by=handled_by)
    log_admin_action("Обновил заявку", f"№{lead_id}", status)
    return "", 204


@bp.post("/api/admin/leads/<int:lead_id>/archive")
@login_required()
def admin_archive_lead(lead_id: int):
    """Архив убирает заявку из рабочего списка, вернуть её можно в любой момент."""
    require_csrf()
    archived = bool(json_object().get("archived", True))
    if not set_lead_archived(lead_id, archived):
        return jsonify({"error": "Заявка не найдена"}), 404
    log_admin_action("Убрал заявку в архив" if archived else "Вернул заявку из архива", f"№{lead_id}")
    return "", 204


@bp.delete("/api/admin/leads/<int:lead_id>")
@login_required("owner")
def admin_delete_lead(lead_id: int):
    """Удаление навсегда — только владельцу: менеджер убирает заявки в архив."""
    require_csrf()
    if not delete_lead(lead_id):
        return jsonify({"error": "Заявка не найдена"}), 404
    log_admin_action("Удалил заявку", f"№{lead_id}")
    return "", 204


@bp.get("/api/admin/leads.csv")
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
        row = [
            lead["id"], lead["created_at"], lead["source"], lead["status"],
            lead["name"], lead["phone"],
            lead["contact_username"] or lead["username"] or "",
            lead["lead_type"], lead["car_interest"], lead["purchase_method"],
            lead["comment"] or "", lead["note"],
            "да" if lead["is_archived"] else "",
            lead["consent_at"],
        ]
        writer.writerow([_csv_cell(value) for value in row])
    log_admin_action("Выгрузил заявки")
    # BOM: без него Excel открывает кириллицу в CSV как набор символов.
    data = "﻿" + buffer.getvalue()
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@bp.get("/api/admin/summary")
@login_required()
def admin_summary():
    return jsonify(catalog_summary())


@bp.get("/api/admin/actions")
@login_required("owner")
def admin_actions():
    return jsonify({"actions": list_actions()})


@bp.post("/api/admin/cars/<car_id>/sold")
@login_required()
def admin_mark_sold(car_id: str):
    require_csrf()
    payload = json_object()
    sold = bool(payload.get("sold", True))
    if not set_car_sold(car_id, sold):
        return jsonify({"error": "Автомобиль не найден"}), 404
    log_admin_action("Отметил продажу" if sold else "Вернул в продажу", car_id)
    return "", 204


@bp.get("/api/admin/session")
@login_required()
def admin_session():
    admin = current_admin()
    return jsonify(
        {
            "user": {
                "id": admin["id"],
                "username": admin["username"],
                "role": admin["role"],
            },
            "csrf_token": get_csrf_token(),
        }
    )


@bp.get("/api/admin/cars")
@login_required()
def admin_cars():
    return jsonify({"cars": list_cars(include_hidden=True)})


@bp.post("/api/admin/cars")
@login_required()
def admin_create_car():
    require_csrf()
    try:
        car = validate_car(json_object(), creating=True)
        save_car(car)
    except (ValueError, sqlite3.IntegrityError) as error:
        return jsonify({"error": str(error)}), 400
    log_admin_action("Создал карточку", car["id"], f"{car['brand']} {car['model']}")
    return jsonify({"car": get_car(car["id"])}), 201


@bp.put("/api/admin/cars/<car_id>")
@login_required()
def admin_update_car(car_id: str):
    require_csrf()
    if get_car(car_id) is None:
        return jsonify({"error": "Автомобиль не найден"}), 404
    try:
        car = validate_car(json_object(), creating=False)
        save_car(car, original_id=car_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    log_admin_action("Изменил карточку", car_id, f"{car['brand']} {car['model']}")
    return jsonify({"car": get_car(car_id)})


@bp.delete("/api/admin/cars/<car_id>")
@login_required("owner")
def admin_delete_car(car_id: str):
    require_csrf()
    if get_car(car_id) is None:
        return jsonify({"error": "Автомобиль не найден"}), 404
    local_urls = delete_car(car_id)
    for url in local_urls:
        _remove_local_upload(url)
    log_admin_action("Удалил карточку", car_id)
    return "", 204


@bp.post("/api/admin/cars/<car_id>/images")
@login_required()
def admin_upload_image(car_id: str):
    require_csrf()
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
            or not valid_image_signature(image)
        ):
            return jsonify(
                {"error": f"«{image.filename}» не является корректным JPG, PNG или WEBP"}
            ), 400
        safe_stem = secure_filename(Path(image.filename).stem)[:40] or "car"
        filename = f"{safe_stem}-{secrets.token_hex(8)}.{extension}"
        image.save(config.UPLOAD_DIR / filename)
        image_id = add_car_image(
            car_id, f"/uploads/{filename}", f"{car['brand']} {car['model']}"
        )
        saved.append({"image_id": image_id, "url": f"/uploads/{filename}"})

    log_admin_action("Загрузил фотографии", car_id, f"{len(saved)} шт.")
    return jsonify({"images": saved, **saved[0]}), 201


@bp.delete("/api/admin/images/<int:image_id>")
@login_required()
def admin_delete_image(image_id: int):
    require_csrf()
    url = delete_car_image(image_id)
    if url is None:
        return jsonify({"error": "Фотография не найдена"}), 404
    _remove_local_upload(url)
    return "", 204


@bp.put("/api/admin/cars/<car_id>/images/order")
@login_required()
def admin_reorder_images(car_id: str):
    require_csrf()
    payload = json_object()
    try:
        image_ids = [int(value) for value in payload.get("image_ids", [])]
        reorder_car_images(car_id, image_ids)
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректный порядок фотографий"}), 400
    return "", 204


@bp.get("/api/admin/users")
@login_required("owner")
def admin_users():
    current = current_admin()
    users = [
        {**user, "can_manage": can_manage(user["role"]) and user["id"] != current["id"]}
        for user in list_admins()
    ]
    return jsonify(
        {"users": users, "assignable_roles": sorted(MANAGEABLE_ROLES[current["role"]], key=ROLE_LEVEL.get)}
    )


@bp.post("/api/admin/users")
@login_required("owner")
def admin_create_user():
    require_csrf()
    payload = json_object()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", "manager"))
    if not USERNAME_RE.fullmatch(username):
        return jsonify({"error": "Некорректный логин"}), 400
    if len(password) < 12:
        return jsonify({"error": "Пароль должен содержать не менее 12 символов"}), 400
    if role not in ROLE_LEVEL:
        return jsonify({"error": "Некорректная роль"}), 400
    if not can_manage(role):
        return jsonify({"error": "Недостаточно прав для этой роли"}), 403
    try:
        admin_id = create_admin(username, generate_password_hash(password), role)
    except sqlite3.IntegrityError:
        return jsonify({"error": "Такой логин уже существует"}), 400
    log_admin_action("Создал учётную запись", username, role)
    return jsonify({"id": admin_id}), 201


@bp.put("/api/admin/users/<int:admin_id>")
@login_required("owner")
def admin_update_user(admin_id: int):
    require_csrf()
    current = current_admin()
    target = get_admin(admin_id)
    if target is None:
        return jsonify({"error": "Пользователь не найден"}), 404
    payload = json_object()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", target["role"]))
    is_active = bool(payload.get("is_active", target["is_active"]))
    if role not in ROLE_LEVEL:
        return jsonify({"error": "Некорректная роль"}), 400
    if not (can_manage(target["role"]) and can_manage(role)):
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
    if admin_id == current["id"]:
        # Остальные сессии со старым паролем закрываются, текущая остаётся.
        session["password_tag"] = password_tag(get_admin(admin_id))
    log_admin_action("Изменил учётную запись", str(target["username"]), role)
    return "", 204


@bp.delete("/api/admin/users/<int:admin_id>")
@login_required("owner")
def admin_delete_user(admin_id: int):
    require_csrf()
    current = current_admin()
    if admin_id == current["id"]:
        return jsonify({"error": "Нельзя удалить собственную учётную запись"}), 400
    target = get_admin(admin_id)
    if target is None:
        return jsonify({"error": "Пользователь не найден"}), 404
    if not can_manage(target["role"]):
        return jsonify({"error": "Недостаточно прав для этой учётной записи"}), 403
    delete_admin(admin_id)
    log_admin_action("Удалил учётную запись", str(target["username"]))
    return "", 204
