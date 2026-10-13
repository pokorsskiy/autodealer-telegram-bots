"""Логирование бота-витрины."""

import logging
import re

import telebot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("showcase-bot")

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
