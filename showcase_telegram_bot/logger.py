"""Логирование и безопасное уведомление администратора об ошибках."""

import logging
import re
from functools import wraps

import telebot
from telebot.apihelper import ApiTelegramException

from config import YOUR_CHAT_ID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("showcase_telegram_bot")

# pyTelegramBotAPI и requests кладут в текст ошибок полный URL запроса
# /bot<токен>/getUpdates. Фильтр стоит на обработчиках вывода, поэтому
# прячет токен и в сообщениях, и в трассировках, откуда бы они ни пришли.
TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


class TokenMaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = TOKEN_RE.sub("<TOKEN>", record.getMessage())
        record.args = ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = TOKEN_RE.sub("<TOKEN>", record.exc_text)
        return True


for _handler in (*logging.getLogger().handlers, *telebot.logger.handlers):
    _handler.addFilter(TokenMaskFilter())


def safe_handler(bot):
    """Не допускает падения polling из-за ошибки в пользовательском сценарии."""
    def decorator(handler):
        @wraps(handler)
        def wrapper(message, *args, **kwargs):
            try:
                return handler(message, *args, **kwargs)
            except Exception:
                logger.exception("Ошибка в обработчике %s", handler.__name__)
                chat = getattr(message, "chat", None)
                if chat is None and getattr(message, "message", None) is not None:
                    chat = message.message.chat
                try:
                    if chat:
                        bot.send_message(chat.id, "Не удалось выполнить действие. Попробуйте ещё раз.")
                except ApiTelegramException:
                    logger.warning("Не удалось сообщить пользователю об ошибке")

                if YOUR_CHAT_ID and (chat is None or chat.id != YOUR_CHAT_ID):
                    try:
                        bot.send_message(
                            YOUR_CHAT_ID,
                            "В боте произошла ошибка. Подробности сохранены в локальном логе.",
                            parse_mode="HTML",
                        )
                    except ApiTelegramException:
                        logger.warning("Не удалось отправить отчёт администратору")
        return wrapper
    return decorator
