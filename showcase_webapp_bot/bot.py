"""Showcase-бот с каталогом и заявками внутри Telegram Web App."""

import html
import json
import re
import time

import telebot
from requests.exceptions import RequestException
from telebot import apihelper, types
from telebot.apihelper import ApiTelegramException

import texts
from config import (
    ADMIN_WEB_APP_URL,
    BASE_DIR,
    DEMO_MODE,
    LEAD_NOTIFY_CONTACTS,
    MENU_COVER_FILE_ID,
    TELEGRAM_ADMINS,
    TELEGRAM_API_URL,
    TOKEN,
    WEB_APP_URL,
    YOUR_CHAT_ID,
)
from database import init_db, save_lead, update_lead
from keyboards import admin_keyboard, prospect_demo_keyboard, take_lead_keyboard, webapp_keyboard
from logger import logger, safe_handler

REQUIRED_FIELDS = ("name", "phone", "car_interest", "purchase_method", "lead_type")
MAX_LENGTHS = {
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
# Так форма отмечает согласие на обработку персональных данных.
CONSENT_VALUES = {"1", "true", "on"}

if not TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN. Укажите его в .env или переменных окружения.")
if DEMO_MODE is None:
    raise RuntimeError("Не задан DEMO_MODE в .env: 1 — демо без заявок, 0 — рабочий бот.")

# Адрес Bot API — из настройки: с российского сервера Telegram доступен
# только через посредника.
apihelper.API_URL = f"{TELEGRAM_API_URL}/bot{{0}}/{{1}}"
apihelper.FILE_URL = f"{TELEGRAM_API_URL}/file/bot{{0}}/{{1}}"
bot = telebot.TeleBot(TOKEN)
MENU_COVER_PATH = BASE_DIR / "menu-cover.jpg"
_menu_cover_file_id_logged = False


def _send_main_menu(
    chat_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup | None,
) -> None:
    """Отправляет главное меню с локальной обложкой или Telegram file_id."""
    global _menu_cover_file_id_logged

    try:
        if MENU_COVER_FILE_ID:
            bot.send_photo(
                chat_id,
                MENU_COVER_FILE_ID,
                caption=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            return

        with MENU_COVER_PATH.open("rb") as cover:
            sent_message = bot.send_photo(
                chat_id,
                cover,
                caption=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )

        photos = getattr(sent_message, "photo", None)
        if not _menu_cover_file_id_logged and photos:
            logger.info(
                "Добавьте в showcase_webapp_bot/.env: MENU_COVER_FILE_ID=%s",
                photos[-1].file_id,
            )
            _menu_cover_file_id_logged = True
    except (OSError, ApiTelegramException, RequestException):
        logger.exception("Не удалось отправить обложку главного меню")
        bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )


def _main_text(first_name: str | None = None) -> str:
    name = f", {html.escape(first_name)}" if first_name else ""
    text = texts.MAIN_MENU.format(name=name)
    return f"{text}\n\n{texts.DEMO_NOTE}" if DEMO_MODE else text


def _parse_lead(raw_data: str) -> dict[str, str] | None:
    try:
        payload = json.loads(raw_data)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    # Без согласия на обработку персональных данных заявку не принимаем.
    if str(payload.get("consent", "")).strip().lower() not in CONSENT_VALUES:
        return None

    lead = {field: str(payload.get(field, "")).strip() for field in MAX_LENGTHS}
    if any(not lead[field] for field in REQUIRED_FIELDS):
        return None
    if any(len(lead[field]) > limit for field, limit in MAX_LENGTHS.items()):
        return None
    if lead["lead_type"] not in LEAD_TYPES:
        return None
    if len(lead["name"]) < 2 or len(re.sub(r"\D", "", lead["phone"])) < 10:
        return None
    if lead["lead_type"] == "manager" and len(lead["comment"]) < 3:
        return None
    return lead


def _notify_admin(user: types.User, lead: dict[str, str], lead_id: int) -> None:
    if not YOUR_CHAT_ID:
        logger.warning("YOUR_CHAT_ID не задан: заявка сохранена без уведомления")
        return

    full_name = html.escape(
        " ".join(
            filter(
                None,
                [getattr(user, "first_name", None), getattr(user, "last_name", None)],
            )
        )
        or lead["name"]
    )
    user_username = getattr(user, "username", None)
    telegram_username = f"@{html.escape(user_username)}" if user_username else "не указан"
    contact_username = html.escape(lead["username"]) or "не указан"
    lead_label = "Заявка на автомобиль" if lead["lead_type"] == "car" else "Помощь с выбором"
    profile = f'<a href="tg://user?id={user.id}">{full_name}</a>'
    if not LEAD_NOTIFY_CONTACTS:
        # Без персональных данных: контакты клиента — только в админке.
        bot.send_message(
            YOUR_CHAT_ID,
            f"🔥 <b>{lead_label} №{lead_id}</b>\n\n"
            f"🚗 <b>Автомобиль:</b> {html.escape(lead['car_interest'])}\n"
            f"💳 <b>Покупка:</b> {html.escape(lead['purchase_method'])}\n\n"
            "Контакты клиента — в админке.",
            parse_mode="HTML",
            reply_markup=take_lead_keyboard(lead_id, ADMIN_WEB_APP_URL, YOUR_CHAT_ID > 0),
        )
        return

    bot.send_message(
        YOUR_CHAT_ID,
        f"🔥 <b>{lead_label} из Web App</b>\n\n"
        f"👤 <b>Клиент:</b> {profile}\n"
        f"✍️ <b>Имя в форме:</b> {html.escape(lead['name'])}\n"
        f"📞 <b>Телефон:</b> <code>{html.escape(lead['phone'])}</code>\n"
        f"💬 <b>Username в форме:</b> {contact_username}\n"
        f"🚗 <b>Автомобиль:</b> {html.escape(lead['car_interest'])}\n"
        f"💳 <b>Покупка:</b> {html.escape(lead['purchase_method'])}\n"
        f"📝 <b>Комментарий:</b> {html.escape(lead['comment']) or '—'}\n\n"
        f"🔗 <b>Telegram:</b> {telegram_username}, <code>{user.id}</code>",
        parse_mode="HTML",
        reply_markup=take_lead_keyboard(lead_id),
    )


def configure_commands() -> None:
    try:
        bot.set_my_commands([types.BotCommand("start", "Открыть Web App")])
        bot.set_chat_menu_button(menu_button=types.MenuButtonCommands(type="commands"))
    except ApiTelegramException:
        logger.exception("Не удалось настроить системное меню Telegram")


# Демо под перегонщика: t.me/<бот>?start=<имя> открывает его каталог и админку.
# Работает только в демо-режиме и только для собранных демо (demos/<имя>/demo.json).
DEMO_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _prospect_demo(message: types.Message) -> bool:
    parts = (getattr(message, "text", "") or "").split(maxsplit=1)
    slug = parts[1].strip() if len(parts) > 1 else ""
    if not DEMO_MODE or not DEMO_SLUG_RE.fullmatch(slug) or not WEB_APP_URL.startswith("https://"):
        return False
    path = BASE_DIR / "demos" / slug / "demo.json"
    try:
        demo = json.loads(path.read_text(encoding="utf-8"))
        brand = str(demo.get("brand", "")).strip()
    except (OSError, ValueError, AttributeError):
        return False
    if not brand:
        return False
    # Срок демо — последний день в expires; дальше каталог и админка не открываются.
    expires = str(demo.get("expires", "")).strip()
    if expires and time.strftime("%Y-%m-%d", time.gmtime()) > expires:
        bot.send_message(
            message.chat.id, texts.PROSPECT_DEMO_ENDED.format(brand=html.escape(brand[:40])),
            parse_mode="HTML",
        )
        logger.info("Демо %s закончилось, кнопки не показаны", slug)
        return True
    site = WEB_APP_URL.split("?", 1)[0].rstrip("/")
    host = site.split("/", 3)[2]
    _send_main_menu(
        message.chat.id,
        texts.PROSPECT_DEMO.format(brand=html.escape(brand[:40])),
        prospect_demo_keyboard(f"{site}/?demo={slug}", f"https://{host}/admin/demo?demo={slug}"),
    )
    logger.info("Открыто демо %s", slug)
    return True


@bot.message_handler(commands=["start"])
@safe_handler(bot)
def start(message: types.Message) -> None:
    if _prospect_demo(message):
        return
    if not WEB_APP_URL.startswith("https://"):
        logger.warning("WEB_APP_URL не задан: кнопка каталога не показана")
        _send_main_menu(message.chat.id, texts.WEBAPP_NOT_CONFIGURED, None)
        return
    _send_main_menu(
        message.chat.id,
        _main_text(message.from_user.first_name),
        webapp_keyboard(WEB_APP_URL),
    )


def _is_telegram_admin(message: types.Message) -> bool:
    return message.from_user.id in TELEGRAM_ADMINS


# Команды нет в меню: остальным /admin ничего не отвечает, как любая
# неизвестная команда. Настоящую проверку доступа делает сервер.
@bot.message_handler(commands=["admin"], func=_is_telegram_admin)
@safe_handler(bot)
def admin(message: types.Message) -> None:
    if not ADMIN_WEB_APP_URL:
        bot.send_message(message.chat.id, texts.WEBAPP_NOT_CONFIGURED)
        return
    bot.send_message(
        message.chat.id,
        texts.ADMIN,
        parse_mode="HTML",
        reply_markup=admin_keyboard(ADMIN_WEB_APP_URL),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("lead:take:"))
@safe_handler(bot)
def take_lead(call: types.CallbackQuery) -> None:
    """Кнопка под уведомлением: статус меняется, не заходя в админку."""
    lead_id = int(call.data.rsplit(":", 1)[1])
    handler = getattr(call.from_user, "username", None) or str(call.from_user.id)
    updated = update_lead(lead_id, status="in_work", note="", handled_by=handler)
    bot.answer_callback_query(
        call.id,
        text="Заявка в работе" if updated else "Заявка не найдена",
    )
    if not updated:
        return
    try:
        bot.edit_message_text(
            f"{call.message.html_text}\n\n✅ <b>В работе:</b> {html.escape(handler)}",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
        )
    except ApiTelegramException:
        logger.exception("Не удалось отметить заявку №%s в сообщении", lead_id)


@bot.message_handler(content_types=["web_app_data"])
@safe_handler(bot)
def handle_webapp_data(message: types.Message) -> None:
    if DEMO_MODE:
        # Демо данные не принимает: заявку не разбираем, не сохраняем и не пересылаем.
        bot.send_message(message.chat.id, texts.LEAD_DEMO)
        return
    lead = _parse_lead(message.web_app_data.data)
    if not lead:
        bot.send_message(
            message.chat.id,
            texts.LEAD_INVALID,
        )
        return

    lead_id = save_lead(message.from_user.id, message.from_user.username, lead)
    _notify_admin(message.from_user, lead, lead_id)
    bot.send_message(
        message.chat.id,
        texts.LEAD_ACCEPTED,
        parse_mode="HTML",
    )


def run_polling() -> None:
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
        except (ApiTelegramException, OSError):
            logger.exception("Ошибка соединения с Telegram. Повтор через 5 секунд.")
            time.sleep(5)


if __name__ == "__main__":
    init_db()
    configure_commands()
    logger.info("Web App showcase-бот запущен")
    run_polling()
