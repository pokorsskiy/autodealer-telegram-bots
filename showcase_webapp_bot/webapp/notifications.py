"""Уведомление менеджеру о заявке через Bot API."""

from html import escape
from typing import Any

import requests
from requests.exceptions import RequestException

import config
from logger import logger


def notify_lead(
    lead_id: int, lead: dict[str, str], telegram_user: dict[str, Any] | None = None
) -> bool:
    """Отправляет заявку владельцу напрямую через Bot API.

    Кроме основного бота заявка уходит в чаты ботов из ADMIN_EXTRA_BOT_TOKENS
    (гибрид): они показывают ту же витрину, и владелец ждёт заявку и там.
    """
    if not config.TOKEN or not config.YOUR_CHAT_ID:
        logger.warning("Заявка не отправлена: не задан токен бота или чат владельца")
        return False

    label = "Заявка на автомобиль" if lead["lead_type"] == "car" else "Помощь с выбором"
    if not config.LEAD_NOTIFY_CONTACTS:
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


def admin_button() -> dict[str, Any] | None:
    """Кнопка админки под уведомлением. Web App-кнопки Telegram разрешает
    только в личном чате, в группе админка открывается ссылкой."""
    if not config.ADMIN_WEB_APP_URL:
        return None
    if config.YOUR_CHAT_ID and config.YOUR_CHAT_ID > 0:
        return {"text": "🔐 Открыть админку", "web_app": {"url": config.ADMIN_WEB_APP_URL}}
    return {"text": "🔐 Открыть админку", "url": config.ADMIN_WEB_APP_URL.removesuffix("/tg")}


def _send_lead_notice(lead_id: int, text: str) -> bool:
    take = [{"text": "Взял в работу", "callback_data": f"lead:take:{lead_id}"}]
    admin = admin_button()
    delivered = False
    for token in [config.TOKEN, *config.ADMIN_EXTRA_BOT_TOKENS]:
        message = {"chat_id": config.YOUR_CHAT_ID, "text": text, "parse_mode": "HTML"}
        # «Взял в работу» обрабатывает только основной бот.
        rows = [take] if token == config.TOKEN else []
        if admin and not config.LEAD_NOTIFY_CONTACTS:
            rows.append([admin])
        if rows:
            message["reply_markup"] = {"inline_keyboard": rows}
        try:
            response = requests.post(
                f"{config.TELEGRAM_API_URL}/bot{token}/sendMessage",
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
