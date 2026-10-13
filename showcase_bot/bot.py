"""Бот-витрина: навигатор по трём ботам-примерам."""

import html
import time
from functools import wraps
from pathlib import Path

import telebot
from telebot.apihelper import ApiTelegramException

import texts
from config import BOT_TOKEN, MENU_COVER_FILE_ID, SHOWCASES
from keyboards import (
    get_about_keyboard,
    get_catalog_keyboard,
    get_main_keyboard,
    get_showcase_keyboard,
)
from logger import logger

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN. Добавьте его в showcase_bot/.env.")

bot = telebot.TeleBot(BOT_TOKEN)
SHOWCASES_BY_KEY = {item["key"]: item for item in SHOWCASES}
MENU_COVER_PATH = Path(__file__).resolve().parent / "menu-cover.jpg"
_menu_cover_file_id_logged = False
STATIC_SCREENS = {
    "about": (texts.ABOUT, get_about_keyboard),
}


def render_catalog() -> str:
    """Описание под каждым примером, чтобы выбирать не заходя в карточку."""
    cards = "\n\n".join(
        f"<b>{html.escape(item['title'])}</b>\n{html.escape(item['tagline'])}"
        for item in SHOWCASES
    )
    return f"{texts.CATALOG_HEADER}\n\n{cards}"


def render_showcase(showcase: dict) -> str:
    """Карточка примера: что умеет бот и на чём он держится."""
    lines = [
        f"<b>{html.escape(showcase['title'])}</b>",
        "",
        html.escape(showcase["tagline"]),
        "",
        "<b>Что умеет:</b>",
        *(f"• {html.escape(item)}" for item in showcase["features"]),
        "",
        "<b>Под капотом:</b>",
        *(f"• {html.escape(item)}" for item in showcase["inside"]),
    ]
    if not showcase["url"]:
        lines += ["", texts.SHOWCASE_NO_LINK]
    return "\n".join(lines)


def safe_handler(handler):
    """Логирует ошибки обработчиков и не раскрывает детали пользователю."""
    @wraps(handler)
    def wrapper(event, *args, **kwargs):
        try:
            return handler(event, *args, **kwargs)
        except Exception:
            logger.exception("Ошибка в обработчике %s", handler.__name__)
    return wrapper


def send_main_menu(chat_id: int) -> None:
    """Отправляет меню через Telegram file_id, если он уже сохранён."""
    global _menu_cover_file_id_logged

    try:
        if MENU_COVER_FILE_ID:
            bot.send_photo(
                chat_id,
                MENU_COVER_FILE_ID,
                caption=texts.MAIN_MENU,
                parse_mode="HTML",
                reply_markup=get_main_keyboard(),
            )
            return

        with MENU_COVER_PATH.open("rb") as cover:
            sent_message = bot.send_photo(
                chat_id,
                cover,
                caption=texts.MAIN_MENU,
                parse_mode="HTML",
                reply_markup=get_main_keyboard(),
            )

        if not _menu_cover_file_id_logged and sent_message.photo:
            logger.info(
                "Добавьте в showcase_bot/.env: MENU_COVER_FILE_ID=%s",
                sent_message.photo[-1].file_id,
            )
            _menu_cover_file_id_logged = True
    except (OSError, ApiTelegramException):
        logger.exception("Не удалось отправить обложку главного меню")
        bot.send_message(
            chat_id,
            texts.MAIN_MENU,
            parse_mode="HTML",
            reply_markup=get_main_keyboard(),
        )


def show_showcase(call: telebot.types.CallbackQuery, showcase: dict) -> None:
    """Карточка примера: видео, а под ним текст и кнопки одним сообщением.

    Без file_id или при ошибке отправки карточка показывается текстом.
    """
    if showcase["video"]:
        try:
            bot.send_video(
                call.message.chat.id,
                showcase["video"],
                caption=render_showcase(showcase),
                parse_mode="HTML",
                reply_markup=get_showcase_keyboard(showcase),
            )
        except ApiTelegramException:
            logger.exception("Не удалось отправить видео карточки %s", showcase["key"])
        else:
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except ApiTelegramException as error:
                if error.error_code != 400:
                    raise
            return
    edit_screen(
        call,
        render_showcase(showcase),
        get_showcase_keyboard(showcase),
        parse_mode="HTML",
    )


def show_main_menu(call: telebot.types.CallbackQuery) -> None:
    """Удаляет текущий экран и показывает главное меню с обложкой."""
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except ApiTelegramException as error:
        if error.error_code != 400:
            raise
    send_main_menu(call.message.chat.id)


def edit_screen(
    call: telebot.types.CallbackQuery,
    text: str,
    reply_markup: telebot.types.InlineKeyboardMarkup,
    parse_mode: str | None = None,
) -> None:
    """Обновляет экран бота в текущем сообщении."""
    # У фото и видео подпись, а не текст: edit_message_text их не меняет.
    if getattr(call.message, "content_type", "") in ("photo", "video"):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except ApiTelegramException as error:
            if error.error_code != 400:
                raise
        bot.send_message(
            call.message.chat.id,
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return
    try:
        bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except ApiTelegramException as error:
        description = (error.description or "").lower()
        if error.error_code == 400 and "message is not modified" in description:
            logger.debug("Экран уже открыт: chat_id=%s", call.message.chat.id)
            return
        raise


@bot.message_handler(commands=["start", "menu"])
@safe_handler
def start(message: telebot.types.Message) -> None:
    send_main_menu(message.chat.id)


@bot.callback_query_handler(func=lambda call: True)
@safe_handler
def handle_callback(call: telebot.types.CallbackQuery) -> None:
    try:
        bot.answer_callback_query(call.id)
    except ApiTelegramException as error:
        if error.error_code == 400:
            logger.info("Устаревший callback %s: %s", call.id, error.description)
        else:
            logger.warning("Не удалось подтвердить callback %s: %s", call.id, error)
    data = call.data

    if data == "menu":
        show_main_menu(call)
        return

    screen = STATIC_SCREENS.get(data)
    if screen:
        text, build_keyboard = screen
        edit_screen(call, text, build_keyboard(), parse_mode="HTML")
        return

    if data == "catalog":
        edit_screen(call, render_catalog(), get_catalog_keyboard(), parse_mode="HTML")
        return

    if data.startswith("showcase:"):
        showcase = SHOWCASES_BY_KEY.get(data.split(":", 1)[1])
        if showcase:
            show_showcase(call, showcase)
        return


@bot.message_handler(content_types=["video", "document"])
@safe_handler
def log_video_file_id(message: telebot.types.Message) -> None:
    """Видео для карточек отправляют боту, а file_id берут из лога.

    file_id у каждого бота свой, поэтому получить его можно только так.
    Подпись к видео помогает понять, для какой карточки ролик.
    """
    video = message.video
    if video is None and message.document and (message.document.mime_type or "").startswith("video/"):
        video = message.document
    if video is not None:
        logger.info(
            "Видео «%s»: %s с, %s МБ, file_id=%s",
            (message.caption or "без подписи")[:40],
            getattr(video, "duration", "?"),
            round((video.file_size or 0) / 1024 / 1024, 1),
            video.file_id,
        )
    send_main_menu(message.chat.id)


@bot.message_handler(content_types=["text"])
@safe_handler
def handle_text(message: telebot.types.Message) -> None:
    """Сообщения не принимаем: на любой текст возвращаем меню."""
    send_main_menu(message.chat.id)


def run_polling() -> None:
    """Перезапускает polling после временных сетевых ошибок."""
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
        except (ApiTelegramException, OSError):
            logger.exception("Ошибка соединения с Telegram. Повтор через 5 секунд.")
            time.sleep(5)


if __name__ == "__main__":
    logger.info("Бот-витрина запущен.")
    run_polling()
