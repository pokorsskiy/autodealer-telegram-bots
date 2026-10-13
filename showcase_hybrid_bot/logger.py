"""Безопасное логирование ошибок гибридного showcase-бота."""

import logging
import re
from functools import wraps

import telebot
from telebot.apihelper import ApiTelegramException

from config import YOUR_CHAT_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("showcase_hybrid_bot")

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
    def decorator(handler):
        @wraps(handler)
        def wrapper(event, *args, **kwargs):
            try:
                return handler(event, *args, **kwargs)
            except Exception:
                logger.exception("Ошибка в обработчике %s", handler.__name__)
                message = getattr(event, "message", event)
                chat_id = getattr(getattr(message, "chat", None), "id", None)
                if chat_id is not None:
                    try:
                        bot.send_message(chat_id, "Временная ошибка. Попробуйте ещё раз.")
                    except ApiTelegramException:
                        logger.exception("Не удалось уведомить пользователя")
                if YOUR_CHAT_ID and YOUR_CHAT_ID != chat_id:
                    try:
                        bot.send_message(
                            YOUR_CHAT_ID,
                            "В Hybrid-боте произошла ошибка. Подробности сохранены в локальном логе.",
                        )
                    except ApiTelegramException:
                        logger.exception("Не удалось уведомить администратора")
        return wrapper
    return decorator
