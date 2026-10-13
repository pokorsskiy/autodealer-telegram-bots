"""Showcase обычного Telegram-бота для автомобильного бизнеса."""

import html
from pathlib import Path
from types import SimpleNamespace

import telebot
from requests.exceptions import RequestException
from telebot import types
from telebot.apihelper import ApiTelegramException

import texts
from calculator import (
    AGE_LABELS,
    DELIVERY_AND_EXPENSES_RUB,
    EUR_RUB_RATE,
    Calculation,
    calculate_from_budget,
    calculate_total_from_rub,
)
from config import DEMO_MODE, MENU_COVER_FILE_ID, TOKEN, YOUR_CHAT_ID
from keyboards import (
    age_menu,
    calculation_menu,
    calculator_cancel,
    calculator_expired,
    calculator_mode_menu,
    faq_answer_menu,
    faq_menu,
    main_menu,
    order_cancel,
    order_confirmation_menu,
    socials_menu,
)
from logger import logger, safe_handler

if not TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN. Скопируйте .env.example в .env и укажите токен.")
if DEMO_MODE is None:
    raise RuntimeError("Не задан DEMO_MODE в .env: 1 — демо без заявок, 0 — рабочий бот.")

bot = telebot.TeleBot(TOKEN)
calculator_sessions: dict[int, dict[str, object]] = {}
order_sessions: dict[int, dict[str, int]] = {}
last_calculations: dict[int, str] = {}
MENU_COVER_PATH = Path(__file__).resolve().parent / "menu-cover.jpg"
_menu_cover_file_id_logged = False

MAIN_TEXT = texts.MAIN_MENU
FAQ_ANSWERS = texts.FAQ_ANSWERS


def _main_text(first_name: str | None = None) -> str:
    name = f", {html.escape(first_name)}" if first_name else ""
    text = MAIN_TEXT.format(name=name)
    return f"{text}\n\n{texts.DEMO_NOTE}" if DEMO_MODE else text


def _order_prompt() -> str:
    return f"{texts.ORDER_PROMPT}\n\n{texts.ORDER_DEMO_NOTE}" if DEMO_MODE else texts.ORDER_PROMPT


def _format_rub(value: int) -> str:
    # Неразрывные пробелы: иначе сумма переносится на две строки на узком экране.
    return f"{value:,}".replace(",", " ")


def _rub(value: int) -> str:
    return f"{_format_rub(value)} ₽"


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


def _format_eur(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


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
        f"<i>{note}Курс расчёта: 1 € = {EUR_RUB_RATE:g} ₽, "
        f"стоимость автомобиля — {_format_eur(calculation.car_price_eur)} €. "
        "Расчёт предварительный: итог зависит от курса, характеристик автомобиля "
        "и расходов на оформление.</i>"
    )


def _manager_lead_text(
    user: types.User,
    request_text: str,
    calculation_summary: str | None,
) -> str:
    full_name = html.escape(
        " ".join(filter(None, [getattr(user, "first_name", None), getattr(user, "last_name", None)]))
        or "Не указано"
    )
    username_value = getattr(user, "username", None)
    username = f"@{html.escape(username_value)}" if username_value else "не указан"
    profile = f'<a href="tg://user?id={user.id}">{full_name}</a>'
    text = (
        "🟠 <b>Новая заявка на заказ автомобиля</b>\n\n"
        f"👤 Клиент: {profile}\n"
        f"💬 Username: {username}\n"
        f"🆔 Telegram ID: <code>{user.id}</code>\n\n"
        f"📝 <b>Запрос клиента</b>\n{html.escape(request_text)}"
    )
    if calculation_summary:
        text += f"\n\n🧮 <b>Последний расчёт клиента</b>\n{calculation_summary}"
    return text


def _answer_callback(call: types.CallbackQuery, text: str | None = None) -> None:
    try:
        bot.answer_callback_query(call.id, text=text)
    except ApiTelegramException as error:
        if error.error_code == 400:
            logger.info("Устаревший callback %s: %s", call.id, error.description)
        else:
            raise


def _edit_screen(
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: types.InlineKeyboardMarkup,
    parse_mode: str | None = "HTML",
) -> None:
    try:
        bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=parse_mode,
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
    if not normalized.isdigit():
        return None
    return int(normalized)


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


def _send_main_menu(chat_id: int, first_name: str | None = None) -> None:
    """Убирает старую reply-клавиатуру и отправляет меню с обложкой."""
    global _menu_cover_file_id_logged

    cleanup_message = bot.send_message(
        chat_id,
        "Клавиатура обновлена.",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    try:
        bot.delete_message(chat_id, cleanup_message.message_id)
    except ApiTelegramException:
        logger.warning("Не удалось удалить техническое сообщение: chat_id=%s", chat_id)

    try:
        if MENU_COVER_FILE_ID:
            bot.send_photo(
                chat_id,
                MENU_COVER_FILE_ID,
                caption=_main_text(first_name),
                parse_mode="HTML",
                reply_markup=main_menu(),
            )
            return

        with MENU_COVER_PATH.open("rb") as cover:
            sent_message = bot.send_photo(
                chat_id,
                cover,
                caption=_main_text(first_name),
                parse_mode="HTML",
                reply_markup=main_menu(),
            )

        photos = getattr(sent_message, "photo", None)
        if not _menu_cover_file_id_logged and photos:
            logger.info(
                "Добавьте в showcase_telegram_bot/.env: MENU_COVER_FILE_ID=%s",
                photos[-1].file_id,
            )
            _menu_cover_file_id_logged = True
    except (OSError, ApiTelegramException, RequestException):
        logger.exception("Не удалось отправить обложку главного меню")
        bot.send_message(
            chat_id,
            _main_text(first_name),
            parse_mode="HTML",
            reply_markup=main_menu(),
        )


def configure_commands() -> None:
    """Показывает кнопку меню Telegram с единственной командой /start."""
    try:
        bot.set_my_commands(
            [types.BotCommand("start", "Запустить бота")]
        )
        bot.set_chat_menu_button(menu_button=types.MenuButtonCommands(type="commands"))
    except ApiTelegramException:
        logger.exception("Не удалось обновить меню команд Telegram")


@bot.message_handler(commands=["start"])
@safe_handler(bot)
def start(message: types.Message) -> None:
    calculator_sessions.pop(message.from_user.id, None)
    order_sessions.pop(message.from_user.id, None)
    _send_main_menu(message.chat.id, message.from_user.first_name)


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

    if data == "order:menu":
        _edit_screen(
            call.message.chat.id,
            call.message.message_id,
            getattr(call.message, "text", None) or texts.ORDER_ACCEPTED,
            reply_markup=None,
            parse_mode=None,
        )
        _send_main_menu(call.message.chat.id, call.from_user.first_name)
        return

    if data == "order":
        order_message_id = _edit_callback_screen(call, _order_prompt(), order_cancel())
        order_sessions[user_id] = {"message_id": order_message_id}
        return

    if data == "order:cancel":
        order_sessions.pop(user_id, None)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except ApiTelegramException as error:
            if error.error_code == 400:
                logger.info("Сообщение заявки уже удалено: %s", call.message.message_id)
            else:
                raise
        _send_main_menu(call.message.chat.id, call.from_user.first_name)
        return

    if data == "calculator":
        calculator_message_id = _edit_callback_screen(
            call,
            f"{texts.CALCULATOR_TITLE}\n\n{texts.CALC_STEP_MODE}",
            calculator_mode_menu(),
        )
        calculator_sessions[user_id] = {
            "step": "mode",
            "message_id": calculator_message_id,
        }
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
        prompt = (
            texts.CALC_STEP_PRICE_BUDGET
            if price_mode == "budget"
            else texts.CALC_STEP_PRICE_KNOWN
        )
        _edit_callback_screen(
            call,
            f"{texts.CALCULATOR_TITLE}\n\n{prompt}",
            calculator_cancel(),
        )
        return

    if data == "calc:cancel":
        calculator_sessions.pop(user_id, None)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except ApiTelegramException as error:
            if error.error_code == 400:
                logger.info("Сообщение калькулятора уже удалено: %s", call.message.message_id)
            else:
                raise
        _send_main_menu(call.message.chat.id, call.from_user.first_name)
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
            f"{texts.CALCULATOR_TITLE}\n\n{texts.CALC_STEP_ENGINE}",
            calculator_cancel(),
        )
        return

    if data == "faq":
        _edit_callback_screen(call, texts.FAQ_INTRO, faq_menu())
        return

    if data.startswith("faq:"):
        answer = FAQ_ANSWERS.get(data.split(":", 1)[1])
        if answer:
            _edit_callback_screen(call, answer, faq_answer_menu())
        return

    if data == "socials":
        _edit_callback_screen(call, texts.SOCIALS, socials_menu())


def _show_demo_order(message: types.Message, order_session: dict[str, int]) -> None:
    """Демо ничего не отправляет: показываем образец заявки с вымышленным клиентом.

    Текст клиента не сохраняется и в образец не попадает. Последний расчёт
    берём настоящий: в нём нет личных данных, а видно, что он приходит вместе с заявкой.
    """
    sample = _manager_lead_text(
        SimpleNamespace(**texts.DEMO_CLIENT),
        texts.DEMO_REQUEST,
        last_calculations.get(message.from_user.id),
    )
    _delete_message(message.chat.id, order_session["message_id"])
    order_sessions.pop(message.from_user.id, None)
    bot.send_message(
        message.chat.id,
        texts.ORDER_DEMO_SAMPLE.format(sample=sample),
        parse_mode="HTML",
    )
    bot.send_message(
        message.chat.id,
        texts.ORDER_DEMO_DONE,
        reply_markup=order_confirmation_menu(),
    )


@bot.message_handler(content_types=["text"])
@safe_handler(bot)
def handle_text(message: types.Message) -> None:
    order_session = order_sessions.get(message.from_user.id)
    if order_session:
        request_text = (message.text or "").strip()
        if not 3 <= len(request_text) <= 1_500:
            bot.send_message(
                message.chat.id,
                texts.ORDER_TEXT_ERROR,
            )
            return
        if DEMO_MODE:
            _show_demo_order(message, order_session)
            return
        if not YOUR_CHAT_ID:
            logger.warning("Заявка не отправлена: не задан YOUR_CHAT_ID")
            bot.send_message(
                message.chat.id,
                texts.ORDER_UNAVAILABLE,
            )
            return

        bot.send_message(
            YOUR_CHAT_ID,
            _manager_lead_text(
                message.from_user,
                request_text,
                last_calculations.get(message.from_user.id),
            ),
            parse_mode="HTML",
        )
        try:
            bot.delete_message(message.chat.id, order_session["message_id"])
        except ApiTelegramException as error:
            if error.error_code != 400:
                raise
            logger.info("Сообщение формы заявки уже удалено: %s", order_session["message_id"])
        order_sessions.pop(message.from_user.id, None)
        bot.send_message(
            message.chat.id,
            texts.ORDER_ACCEPTED,
            reply_markup=order_confirmation_menu(),
        )
        return

    session = calculator_sessions.get(message.from_user.id)
    if not session:
        _send_main_menu(message.chat.id, message.from_user.first_name)
        return

    if session.get("step") == "price":
        price_rub = _parse_rub_price(message.text or "")
        if price_rub is None or not 50_000 <= price_rub <= 50_000_000:
            bot.send_message(
                message.chat.id,
                texts.CALC_PRICE_ERROR,
                parse_mode="HTML",
            )
            return
        session["car_price_rub"] = price_rub
        session["step"] = "age"
        _move_calculator_panel(
            message.chat.id,
            session,
            f"{texts.CALCULATOR_TITLE}\n\n{texts.CALC_STEP_AGE}",
            age_menu(),
        )
        return

    if session.get("step") == "engine":
        engine_liters = _parse_engine_liters(message.text or "")
        if engine_liters is None or not 0.5 <= engine_liters <= 10:
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
                eur_rub_rate=EUR_RUB_RATE,
                delivery_rub=DELIVERY_AND_EXPENSES_RUB,
                other_costs_rub=0,
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
                eur_rub_rate=EUR_RUB_RATE,
                delivery_rub=DELIVERY_AND_EXPENSES_RUB,
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
        # видно, а панель шагов и старое меню убираем.
        _delete_message(message.chat.id, int(session["message_id"]))
        last_calculations[message.from_user.id] = (
            f"Стоимость: {_rub(calculation.car_price_rub)}\n"
            f"Возраст: {AGE_LABELS[age]}\n"
            f"Двигатель: {engine_liters:.1f} л ({_format_rub(engine_cc)} см³)\n"
            f"Итого: {_rub(calculation.total_rub)}"
        )
        calculator_sessions.pop(message.from_user.id, None)
        bot.send_message(message.chat.id, result_text, parse_mode="HTML")
        bot.send_message(
            message.chat.id,
            texts.CALC_NEXT,
            reply_markup=calculation_menu(),
        )


def run_polling() -> None:
    try:
        bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
    except KeyboardInterrupt:
        logger.info("Остановка Telegram showcase-бота по Ctrl+C")
    finally:
        bot.stop_polling()


if __name__ == "__main__":
    configure_commands()
    logger.info("Telegram showcase-бот запущен")
    run_polling()
