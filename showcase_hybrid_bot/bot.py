"""Hybrid showcase: быстрые действия в Telegram и каталог в Web App."""

import hashlib
import hmac
import html
import json
import re
import time
from pathlib import Path

import requests
import telebot
from requests.exceptions import RequestException
from telebot import apihelper, types
from telebot.apihelper import ApiTelegramException

import texts
from calculator import (
    AGE_LABELS,
    WEBAPP_DELIVERY_AND_EXPENSES_RUB,
    WEBAPP_EUR_RUB_RATE,
    Calculation,
    calculate_from_budget,
    calculate_total_from_rub,
)
from config import (
    ADMIN_LEADS_URL,
    ADMIN_WEB_APP_URL,
    DEMO_MODE,
    LEAD_NOTIFY_CONTACTS,
    MENU_COVER_FILE_ID,
    TELEGRAM_ADMIN_IDS,
    TELEGRAM_API_URL,
    TOKEN,
    WEB_APP_URL,
    YOUR_CHAT_ID,
)
from database import init_db, save_lead
from keyboards import (
    admin_keyboard,
    age_menu,
    calculation_menu,
    calculator_cancel,
    calculator_expired,
    calculator_mode_menu,
    faq_answer_menu,
    faq_menu,
    main_menu,
    manager_menu,
    socials_menu,
    webapp_keyboard,
)
from logger import logger, safe_handler

REQUIRED_WEBAPP_FIELDS = (
    "name",
    "phone",
    "car_interest",
    "purchase_method",
    "lead_type",
)
WEBAPP_MAX_LENGTHS = {
    "name": 80,
    "phone": 30,
    "username": 64,
    "car_interest": 80,
    "purchase_method": 40,
    "comment": 500,
    "lead_type": 20,
    "car_id": 80,
}
WEBAPP_LEAD_TYPES = {"car", "manager"}
# Так форма отмечает согласие на обработку персональных данных.
CONSENT_VALUES = {"1", "true", "on"}

FAQ_ANSWERS = texts.FAQ_ANSWERS
PRICE_STEP_RUB = 10_000

if not TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN. Укажите его в .env или переменных окружения.")
if DEMO_MODE is None:
    raise RuntimeError("Не задан DEMO_MODE в .env: 1 — демо без заявок, 0 — рабочий бот.")

# Адрес Bot API — из настройки: с российского сервера Telegram доступен
# только через посредника.
apihelper.API_URL = f"{TELEGRAM_API_URL}/bot{{0}}/{{1}}"
apihelper.FILE_URL = f"{TELEGRAM_API_URL}/file/bot{{0}}/{{1}}"
bot = telebot.TeleBot(TOKEN)
calculator_sessions: dict[int, dict[str, object]] = {}
CALCULATOR_TITLE = texts.CALCULATOR_TITLE
MENU_COVER_PATH = Path(__file__).resolve().parent / "menu-cover.jpg"
_menu_cover_file_id_logged = False


def _main_text(first_name: str | None = None) -> str:
    name = f", {html.escape(first_name)}" if first_name else ""
    text = texts.MAIN_MENU.format(name=name)
    return f"{text}\n\n{texts.DEMO_NOTE}" if DEMO_MODE else text


def _format_rub(value: int) -> str:
    # Неразрывные пробелы: иначе сумма переносится на две строки на узком экране.
    return f"{value:,}".replace(",", " ")


def _rub(value: int) -> str:
    return f"{_format_rub(value)} ₽"


def _calculation_text(
    calculation: Calculation,
    age: str,
    engine_liters: float,
    engine_cc: int,
    budget_rub: int | None = None,
) -> str:
    """Итог расчёта построчно: видно, из чего складывается сумма.

    При расчёте от бюджета показываем подобранную цену автомобиля и остаток,
    иначе — сумму, в которую обойдётся привоз известной машины.
    """
    delivery_and_costs = calculation.delivery_rub + calculation.other_costs_rub
    if budget_rub is None:
        header = "🧮 <b>Ориентировочный расчёт</b>"
        price_line = f"🚘 Стоимость автомобиля: <b>{_rub(calculation.car_price_rub)}</b>"
        total_line = f"<b>Итого: {_rub(calculation.total_rub)}</b>"
        note = ""
    else:
        header = "🧮 <b>Что помещается в бюджет</b>"
        price_line = (
            f"🚘 Автомобиль за границей: <b>до {_rub(calculation.car_price_rub)}</b>"
        )
        total_line = (
            f"<b>Итого: {_rub(calculation.total_rub)}</b> "
            f"из бюджета {_rub(budget_rub)}\n"
            f"Остаётся: {_rub(budget_rub - calculation.total_rub)}"
        )
        note = "Цена автомобиля подобрана под ваш бюджет. "
    return (
        f"{header}\n\n"
        f"Возраст: {AGE_LABELS[age]}, двигатель {engine_liters:.1f} л "
        f"({_format_rub(engine_cc)} см³)\n\n"
        f"{price_line}\n"
        f"🛃 Таможенная пошлина: <b>{_rub(calculation.duty_rub)}</b>\n"
        f"♻️ Утилизационный сбор: <b>{_rub(calculation.recycling_rub)}</b>\n"
        f"🚚 Доставка и расходы: <b>{_rub(delivery_and_costs)}</b>\n\n"
        f"{total_line}\n\n"
        f"<i>{note}Предварительный расчёт по условному курсу "
        f"1 € = {WEBAPP_EUR_RUB_RATE:g} ₽. "
        "Точную стоимость уточнит менеджер.</i>"
    )


def _delete_message(chat_id: int, message_id: int) -> None:
    try:
        bot.delete_message(chat_id, message_id)
    except ApiTelegramException as error:
        if error.error_code != 400:
            raise
        logger.info("Сообщение уже удалено: %s", message_id)


def _move_calculator_panel(
    chat_id: int,
    session: dict[str, object],
    text: str,
    reply_markup: types.InlineKeyboardMarkup,
) -> None:
    """Переносит панель расчёта вниз чата.

    Шаги с кнопками правятся на месте, но после текстового ответа панель
    оказывается выше сообщения пользователя, поэтому её пересылаем заново.
    """
    _delete_message(chat_id, int(session["message_id"]))
    sent_message = bot.send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )
    session["message_id"] = sent_message.message_id


def _parse_number(value: str) -> float | None:
    normalized = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def _parse_rub_price(value: str) -> int | None:
    normalized = (
        value.lower()
        .replace("₽", "")
        .replace("руб.", "")
        .replace("руб", "")
        .replace("\xa0", "")
        .replace(" ", "")
    )
    return int(normalized) if normalized.isdigit() else None


def _parse_engine_liters(value: str) -> float | None:
    normalized = (
        value.lower()
        .replace("литров", "")
        .replace("литра", "")
        .replace("литр", "")
        .replace("л.", "")
        .replace("л", "")
        .strip()
    )
    return _parse_number(normalized)


def _parse_webapp_lead(raw_data: str) -> dict[str, str] | None:
    try:
        payload = json.loads(raw_data)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    # Без согласия на обработку персональных данных заявку не принимаем.
    if str(payload.get("consent", "")).strip().lower() not in CONSENT_VALUES:
        return None

    lead = {
        field: str(payload.get(field, "")).strip()
        for field in WEBAPP_MAX_LENGTHS
    }
    if any(not lead[field] for field in REQUIRED_WEBAPP_FIELDS):
        return None
    if any(
        len(lead[field]) > max_length
        for field, max_length in WEBAPP_MAX_LENGTHS.items()
    ):
        return None
    if lead["lead_type"] not in WEBAPP_LEAD_TYPES:
        return None
    if len(lead["name"]) < 2 or len(re.sub(r"\D", "", lead["phone"])) < 10:
        return None
    if lead["lead_type"] == "manager" and len(lead["comment"]) < 3:
        return None
    return lead


def _profile_text(user: types.User) -> str:
    full_name = html.escape(
        " ".join(
            filter(
                None,
                [getattr(user, "first_name", None), getattr(user, "last_name", None)],
            )
        )
        or "Без имени"
    )
    return f'<a href="tg://user?id={user.id}">{full_name}</a>'


def _send_lead_to_admin(user: types.User, lead: dict[str, str]) -> None:
    """Передаёт заявку в админку витрины, где её ведут вместе с остальными.

    Запрос подписан токеном бота: сервер витрины знает его из
    ADMIN_EXTRA_BOT_TOKENS. Сбой не мешает клиенту: заявка уже сохранена
    здесь и отправлена менеджеру в Telegram.
    """
    if not ADMIN_LEADS_URL:
        return
    body = json.dumps(
        {
            # Заявка без согласия сюда не доходит, а витрина проверяет его ещё раз.
            "lead": {**lead, "consent": "1"},
            "user_id": user.id,
            "username": getattr(user, "username", None),
            "sent_at": int(time.time()),
        },
        ensure_ascii=False,
    ).encode()
    signature = hmac.new(TOKEN.encode(), body, hashlib.sha256).hexdigest()
    try:
        response = requests.post(
            ADMIN_LEADS_URL,
            data=body,
            headers={"Content-Type": "application/json", "X-Bot-Signature": signature},
            timeout=10,
        )
        response.raise_for_status()
    except RequestException:
        logger.exception("Заявка не передана в админку витрины")


def _notify_webapp_lead(user: types.User, lead: dict[str, str]) -> None:
    if not YOUR_CHAT_ID:
        logger.warning("YOUR_CHAT_ID не задан: Web App-заявка сохранена без уведомления")
        return
    telegram_username = getattr(user, "username", None)
    telegram_username_text = (
        f"@{html.escape(telegram_username)}" if telegram_username else "не указан"
    )
    contact_username = html.escape(lead["username"]) or "не указан"
    lead_label = (
        "Заявка на автомобиль"
        if lead["lead_type"] == "car"
        else "Помощь с выбором"
    )
    if not LEAD_NOTIFY_CONTACTS:
        # Без персональных данных: контакты клиента — только в админке.
        bot.send_message(
            YOUR_CHAT_ID,
            f"🔥 <b>{lead_label}</b>\n\n"
            f"🚗 <b>Автомобиль:</b> {html.escape(lead['car_interest'])}\n"
            f"💳 <b>Покупка:</b> {html.escape(lead['purchase_method'])}\n\n"
            "Контакты клиента — в админке.",
            parse_mode="HTML",
            reply_markup=admin_keyboard(ADMIN_WEB_APP_URL) if ADMIN_WEB_APP_URL and YOUR_CHAT_ID > 0 else None,
        )
        return
    bot.send_message(
        YOUR_CHAT_ID,
        f"🔥 <b>{lead_label}</b>\n\n"
        "📍 <b>Источник:</b> Web App\n"
        f"👤 <b>Клиент:</b> {_profile_text(user)}\n"
        f"✍️ <b>Имя в форме:</b> {html.escape(lead['name'])}\n"
        f"📞 <b>Телефон:</b> <code>{html.escape(lead['phone'])}</code>\n"
        f"💬 <b>Username в форме:</b> {contact_username}\n"
        f"🚗 <b>Автомобиль:</b> {html.escape(lead['car_interest'])}\n"
        f"💳 <b>Покупка:</b> {html.escape(lead['purchase_method'])}\n"
        f"📝 <b>Комментарий:</b> {html.escape(lead['comment']) or '—'}\n\n"
        f"🔗 <b>Telegram:</b> {telegram_username_text}, <code>{user.id}</code>",
        parse_mode="HTML",
    )


def _answer_callback(call: types.CallbackQuery, text: str | None = None) -> None:
    try:
        bot.answer_callback_query(call.id, text=text)
    except ApiTelegramException as error:
        if error.error_code == 400:
            logger.info("Устаревший callback %s", call.id)
            return
        raise


def _edit_screen(
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup,
) -> None:
    try:
        bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except ApiTelegramException as error:
        description = (error.description or "").lower()
        if error.error_code == 400 and "message is not modified" in description:
            return
        raise


def _edit_callback_screen(
    call: types.CallbackQuery,
    text: str,
    reply_markup: types.InlineKeyboardMarkup,
) -> int:
    if getattr(call.message, "content_type", "") == "photo":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except ApiTelegramException as error:
            if error.error_code != 400:
                raise
        sent_message = bot.send_message(
            call.message.chat.id,
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        return sent_message.message_id

    _edit_screen(call.message.chat.id, call.message.message_id, text, reply_markup)
    return call.message.message_id


def _send_main_menu(chat_id: int, first_name: str | None = None) -> None:
    global _menu_cover_file_id_logged

    _remove_reply_keyboard(chat_id)
    try:
        if MENU_COVER_FILE_ID:
            bot.send_photo(
                chat_id,
                MENU_COVER_FILE_ID,
                caption=_main_text(first_name),
                parse_mode="HTML",
                reply_markup=main_menu(WEB_APP_URL),
            )
            return

        with MENU_COVER_PATH.open("rb") as cover:
            sent_message = bot.send_photo(
                chat_id,
                cover,
                caption=_main_text(first_name),
                parse_mode="HTML",
                reply_markup=main_menu(WEB_APP_URL),
            )

        photos = getattr(sent_message, "photo", None)
        if not _menu_cover_file_id_logged and photos:
            logger.info(
                "Добавьте в showcase_hybrid_bot/.env: MENU_COVER_FILE_ID=%s",
                photos[-1].file_id,
            )
            _menu_cover_file_id_logged = True
    except (OSError, ApiTelegramException, RequestException):
        logger.exception("Не удалось отправить обложку главного меню")
        bot.send_message(
            chat_id,
            _main_text(first_name),
            parse_mode="HTML",
            reply_markup=main_menu(WEB_APP_URL),
        )


def _remove_reply_keyboard(chat_id: int) -> None:
    cleanup = bot.send_message(
        chat_id,
        "Клавиатура обновлена.",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    try:
        bot.delete_message(chat_id, cleanup.message_id)
    except ApiTelegramException:
        logger.warning("Не удалось удалить техническое сообщение: chat_id=%s", chat_id)


def configure_commands() -> None:
    try:
        bot.set_my_commands(
            [
                types.BotCommand("start", "Запустить бота"),
                types.BotCommand("menu", "Открыть меню"),
                types.BotCommand("site", "Открыть Web App"),
            ]
        )
        bot.set_chat_menu_button(menu_button=types.MenuButtonCommands(type="commands"))
    except ApiTelegramException:
        logger.exception("Не удалось обновить меню команд Telegram")


@bot.message_handler(commands=["start", "menu"])
@safe_handler(bot)
def start(message: types.Message) -> None:
    calculator_sessions.pop(message.from_user.id, None)
    _send_main_menu(message.chat.id, message.from_user.first_name)


@bot.message_handler(commands=["site"])
@safe_handler(bot)
def site(message: types.Message) -> None:
    calculator_sessions.pop(message.from_user.id, None)
    _remove_reply_keyboard(message.chat.id)
    if not WEB_APP_URL.startswith("https://"):
        bot.send_message(
            message.chat.id,
            texts.WEBAPP_NOT_CONFIGURED,
        )
        return
    bot.send_message(
        message.chat.id,
        texts.SITE,
        parse_mode="HTML",
        reply_markup=webapp_keyboard(WEB_APP_URL),
    )


def _is_telegram_admin(message: types.Message) -> bool:
    return message.from_user.id in TELEGRAM_ADMIN_IDS


# Команды нет в меню: у остальных /admin уходит в обычный обработчик текста
# и показывает главное меню. Настоящую проверку доступа делает сервер.
@bot.message_handler(commands=["admin"], func=_is_telegram_admin)
@safe_handler(bot)
def admin(message: types.Message) -> None:
    calculator_sessions.pop(message.from_user.id, None)
    _remove_reply_keyboard(message.chat.id)
    if not ADMIN_WEB_APP_URL:
        bot.send_message(message.chat.id, texts.WEBAPP_NOT_CONFIGURED)
        return
    bot.send_message(
        message.chat.id,
        texts.ADMIN,
        parse_mode="HTML",
        reply_markup=admin_keyboard(ADMIN_WEB_APP_URL),
    )


@bot.callback_query_handler(func=lambda call: True)
@safe_handler(bot)
def handle_callback(call: types.CallbackQuery) -> None:
    data = call.data or ""
    user_id = call.from_user.id

    _answer_callback(call)

    if data == "menu":
        calculator_sessions.pop(user_id, None)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except ApiTelegramException as error:
            if error.error_code != 400:
                raise
        _send_main_menu(call.message.chat.id, call.from_user.first_name)
        return

    if data == "calculator":
        calculator_message_id = _edit_callback_screen(
            call,
            f"{CALCULATOR_TITLE}\n\n{texts.CALC_STEP_MODE}",
            calculator_mode_menu(),
        )
        calculator_sessions[user_id] = {
            "step": "mode",
            "message_id": calculator_message_id,
        }
        return

    if data == "calc:cancel":
        calculator_sessions.pop(user_id, None)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except ApiTelegramException as error:
            if error.error_code != 400:
                raise
        _send_main_menu(call.message.chat.id, call.from_user.first_name)
        return

    if data == "manager":
        _edit_callback_screen(call, texts.MANAGER, manager_menu(WEB_APP_URL))
        return

    if data.startswith("calc:mode:"):
        session = calculator_sessions.get(user_id)
        if not session or session.get("step") != "mode":
            _edit_callback_screen(call, texts.CALC_EXPIRED, calculator_expired())
            return
        price_mode = data.removeprefix("calc:mode:")
        if price_mode not in {"known", "budget"}:
            return
        session["price_mode"] = price_mode
        session["step"] = "price"
        if price_mode == "budget":
            price_prompt = texts.CALC_STEP_PRICE_BUDGET
        else:
            price_prompt = texts.CALC_STEP_PRICE_KNOWN
        _edit_callback_screen(
            call,
            f"{CALCULATOR_TITLE}\n\n{price_prompt}",
            calculator_cancel(),
        )
        return

    if data.startswith("calc:age:"):
        session = calculator_sessions.get(user_id)
        if not session or session.get("step") != "age":
            _edit_callback_screen(call, texts.CALC_EXPIRED, calculator_expired())
            return
        age = data.removeprefix("calc:age:")
        if age not in AGE_LABELS:
            return
        session["age"] = age
        session["step"] = "engine"
        _edit_callback_screen(
            call,
            f"{CALCULATOR_TITLE}\n\n{texts.CALC_STEP_ENGINE}",
            calculator_cancel(),
        )
        return

    if data == "faq":
        _edit_callback_screen(call, texts.FAQ_INTRO, faq_menu())
        return

    if data.startswith("faq:"):
        answer = FAQ_ANSWERS.get(data.split(":", 1)[1])
        if answer:
            _edit_callback_screen(
                call,
                answer,
                faq_answer_menu(),
            )
        return

    if data == "socials":
        _edit_callback_screen(call, texts.SOCIALS, socials_menu())


@bot.message_handler(content_types=["web_app_data"])
@safe_handler(bot)
def handle_webapp_data(message: types.Message) -> None:
    if DEMO_MODE:
        # Демо данные не принимает: заявку не разбираем, не сохраняем и не пересылаем.
        bot.send_message(message.chat.id, texts.WEBAPP_LEAD_DEMO)
        return
    lead = _parse_webapp_lead(message.web_app_data.data)
    if not lead:
        bot.send_message(
            message.chat.id,
            texts.WEBAPP_LEAD_INVALID,
        )
        return
    save_lead(
        message.from_user.id,
        message.from_user.username,
        f"webapp_{lead['lead_type']}",
        lead["car_interest"],
        lead["phone"],
    )
    _notify_webapp_lead(message.from_user, lead)
    _send_lead_to_admin(message.from_user, lead)
    bot.send_message(
        message.chat.id,
        texts.WEBAPP_LEAD_ACCEPTED,
        parse_mode="HTML",
    )


@bot.message_handler(content_types=["text"])
@safe_handler(bot)
def handle_text(message: types.Message) -> None:
    user_id = message.from_user.id
    session = calculator_sessions.get(user_id)
    if not session:
        _send_main_menu(message.chat.id, message.from_user.first_name)
        return

    if session.get("step") == "price":
        price_rub = _parse_rub_price(message.text or "")
        if price_rub is None or not 50_000 <= price_rub <= 50_000_000:
            bot.send_message(
                message.chat.id,
                texts.CALC_PRICE_OUT_OF_RANGE,
                parse_mode="HTML",
            )
            return
        # Расчёт предварительный, поэтому некруглую сумму округляем, а не отвергаем.
        # Считаем на целых: round() округляет половину к чётному и даёт скачки.
        session["car_price_rub"] = (
            (price_rub + PRICE_STEP_RUB // 2) // PRICE_STEP_RUB * PRICE_STEP_RUB
        )
        session["step"] = "age"
        _move_calculator_panel(
            message.chat.id,
            session,
            f"{CALCULATOR_TITLE}\n\n{texts.CALC_STEP_AGE}",
            age_menu(),
        )
        return

    if session.get("step") == "engine":
        engine_liters = _parse_engine_liters(message.text or "")
        if (
            engine_liters is None
            or not 0.5 <= engine_liters <= 10
            or abs(engine_liters * 10 - round(engine_liters * 10)) > 1e-9
        ):
            bot.send_message(
                message.chat.id,
                texts.CALC_ENGINE_ERROR,
                parse_mode="HTML",
            )
            return
        engine_cc = round(engine_liters * 1000)
        age = str(session["age"])
        amount_rub = int(session["car_price_rub"])
        is_budget = session.get("price_mode") == "budget"
        if is_budget:
            calculation = calculate_from_budget(
                budget_rub=amount_rub,
                age=age,
                engine_cc=engine_cc,
                eur_rub_rate=WEBAPP_EUR_RUB_RATE,
                delivery_rub=WEBAPP_DELIVERY_AND_EXPENSES_RUB,
                other_costs_rub=0,
                price_step_rub=PRICE_STEP_RUB,
            )
            if calculation is None:
                # Бюджет меньше обязательных расходов: возвращаем на ввод суммы.
                bot.send_message(
                    message.chat.id,
                    texts.CALC_BUDGET_TOO_SMALL,
                    parse_mode="HTML",
                )
                return
        else:
            calculation = calculate_total_from_rub(
                car_price_rub=amount_rub,
                age=age,
                engine_cc=engine_cc,
                eur_rub_rate=WEBAPP_EUR_RUB_RATE,
                delivery_rub=WEBAPP_DELIVERY_AND_EXPENSES_RUB,
                other_costs_rub=0,
            )
        result_text = _calculation_text(
            calculation,
            age=age,
            engine_liters=engine_liters,
            engine_cc=engine_cc,
            budget_rub=amount_rub if is_budget else None,
        )
        # Результат остаётся в переписке отдельным сообщением: прошлые расчёты
        # видно, а панель шагов убираем. Действия выносим в следующее сообщение,
        # чтобы кнопки не висели на старых расчётах.
        _delete_message(message.chat.id, int(session["message_id"]))
        calculator_sessions.pop(user_id, None)
        bot.send_message(message.chat.id, result_text, parse_mode="HTML")
        bot.send_message(
            message.chat.id,
            texts.CALC_NEXT,
            reply_markup=calculation_menu(
                WEB_APP_URL,
                amount_rub if is_budget else calculation.total_rub,
                age,
            ),
        )


def run_polling() -> None:
    while True:
        try:
            bot.infinity_polling(
                skip_pending=True,
                timeout=30,
                long_polling_timeout=30,
            )
        except KeyboardInterrupt:
            logger.info("Остановка Hybrid showcase-бота по Ctrl+C")
            bot.stop_polling()
            return
        except (ApiTelegramException, OSError):
            logger.exception("Ошибка соединения с Telegram. Повтор через 5 секунд.")
            time.sleep(5)


if __name__ == "__main__":
    init_db()
    configure_commands()
    logger.info("Hybrid showcase-бот запущен")
    run_polling()
