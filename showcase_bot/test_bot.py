"""Проверка экранов витрины без подключения к Telegram."""

import logging
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from telebot.apihelper import ApiTelegramException

os.environ.setdefault("BOT_TOKEN", "test-token")

import bot as bot_module
import config as config_module
import keyboards as keyboards_module
import logger as logger_module


def callback(data: str, content_type: str = "text") -> SimpleNamespace:
    return SimpleNamespace(
        id=f"callback-{data}",
        data=data,
        message=SimpleNamespace(
            chat=SimpleNamespace(id=202), message_id=303, content_type=content_type
        ),
    )


def api_error(code: int, description: str) -> ApiTelegramException:
    return ApiTelegramException(
        "editMessageText", Mock(), {"error_code": code, "description": description}
    )


def button_texts(markup) -> list[str]:
    return [button.text for row in markup.keyboard for button in row]


class ConfigTest(unittest.TestCase):
    def test_telegram_links_are_normalized(self) -> None:
        self.assertEqual(config_module.normalize_telegram_url("@demo_bot"), "https://t.me/demo_bot")
        self.assertEqual(config_module.normalize_telegram_url("t.me/demo_bot"), "https://t.me/demo_bot")
        self.assertEqual(config_module.normalize_telegram_url("demo_bot"), "")

    def test_only_https_is_accepted_for_buttons(self) -> None:
        self.assertEqual(config_module.https_url(" https://example.com/admin/demo "), "https://example.com/admin/demo")
        self.assertEqual(config_module.https_url("http://example.com"), "")


class KeyboardTest(unittest.TestCase):
    def test_source_button_appears_only_with_repo_url(self) -> None:
        with patch.object(keyboards_module, "REPO_URL", ""):
            self.assertNotIn("💻 Исходный код", button_texts(keyboards_module.get_main_keyboard()))
        with patch.object(keyboards_module, "REPO_URL", "https://github.com/demo/repo"):
            self.assertIn("💻 Исходный код", button_texts(keyboards_module.get_main_keyboard()))

    def test_catalog_lists_every_showcase(self) -> None:
        texts = button_texts(keyboards_module.get_catalog_keyboard())
        for item in config_module.SHOWCASES:
            self.assertIn(item["title"], texts)

    def test_admin_button_only_for_showcases_with_admin(self) -> None:
        basic, webapp, _hybrid = config_module.SHOWCASES
        with patch.object(keyboards_module, "ADMIN_DEMO_URL", "https://example.com/admin/demo"):
            self.assertNotIn("🔐 Попробовать админку", button_texts(keyboards_module.get_showcase_keyboard(basic)))
            self.assertIn("🔐 Попробовать админку", button_texts(keyboards_module.get_showcase_keyboard(webapp)))

    def test_showcase_without_link_has_no_open_button(self) -> None:
        showcase = {**config_module.SHOWCASES[0], "url": ""}
        self.assertNotIn("▶️ Открыть бота", button_texts(keyboards_module.get_showcase_keyboard(showcase)))
        self.assertIn(bot_module.texts.SHOWCASE_NO_LINK, bot_module.render_showcase(showcase))


class RenderTest(unittest.TestCase):
    def test_showcase_card_escapes_html(self) -> None:
        showcase = {
            **config_module.SHOWCASES[0],
            "title": "<b>Каталог</b>",
            "features": ("Цена < 1 млн & выше",),
        }
        card = bot_module.render_showcase(showcase)
        self.assertIn("&lt;b&gt;Каталог&lt;/b&gt;", card)
        self.assertIn("Цена &lt; 1 млн &amp; выше", card)

    def test_cards_fit_into_video_caption(self) -> None:
        # Подпись к видео в Telegram — не длиннее 1024 символов.
        for showcase in config_module.SHOWCASES:
            self.assertLessEqual(len(bot_module.render_showcase(showcase)), 1024, showcase["key"])

    def test_catalog_mentions_every_showcase(self) -> None:
        catalog = bot_module.render_catalog()
        for item in config_module.SHOWCASES:
            self.assertIn(item["title"], catalog)


class CallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(bot_module, "bot")
        self.bot = patcher.start()
        self.addCleanup(patcher.stop)

    def test_text_screen_is_edited_in_place(self) -> None:
        bot_module.handle_callback(callback("about"))
        self.bot.answer_callback_query.assert_called_once()
        self.bot.edit_message_text.assert_called_once()
        self.assertEqual(self.bot.edit_message_text.call_args.args[0], bot_module.texts.ABOUT)
        self.bot.send_message.assert_not_called()

    def test_screen_after_photo_is_sent_as_new_message(self) -> None:
        """Сообщение с фото нельзя превратить в текст: оно удаляется, экран отправляется заново."""
        bot_module.handle_callback(callback("catalog", content_type="photo"))
        self.bot.delete_message.assert_called_once_with(202, 303)
        self.bot.send_message.assert_called_once()
        self.bot.edit_message_text.assert_not_called()

    def test_repeated_press_does_not_raise(self) -> None:
        self.bot.edit_message_text.side_effect = api_error(400, "Bad Request: message is not modified")
        bot_module.edit_screen(callback("about"), "текст", Mock())

    def test_other_api_errors_are_not_swallowed_by_edit_screen(self) -> None:
        self.bot.edit_message_text.side_effect = api_error(403, "Forbidden: bot was blocked by the user")
        with self.assertRaises(ApiTelegramException):
            bot_module.edit_screen(callback("about"), "текст", Mock())

    def test_showcase_with_video_is_sent_as_video(self) -> None:
        showcase = {**config_module.SHOWCASES[1], "video": "video-file-id"}
        with patch.dict(bot_module.SHOWCASES_BY_KEY, {"webapp": showcase}):
            bot_module.handle_callback(callback("showcase:webapp"))
        self.bot.send_video.assert_called_once()
        self.assertEqual(self.bot.send_video.call_args.args[1], "video-file-id")
        self.bot.delete_message.assert_called_once_with(202, 303)

    def test_showcase_falls_back_to_text_when_video_fails(self) -> None:
        showcase = {**config_module.SHOWCASES[1], "video": "broken-id"}
        self.bot.send_video.side_effect = api_error(400, "Bad Request: wrong file identifier")
        with (
            patch.dict(bot_module.SHOWCASES_BY_KEY, {"webapp": showcase}),
            self.assertLogs("showcase-bot", level="ERROR"),
        ):
            bot_module.handle_callback(callback("showcase:webapp"))
        self.bot.edit_message_text.assert_called_once()

    def test_unknown_callback_is_ignored(self) -> None:
        bot_module.handle_callback(callback("showcase:missing"))
        bot_module.handle_callback(callback("price"))
        self.bot.edit_message_text.assert_not_called()
        self.bot.send_message.assert_not_called()

    def test_menu_falls_back_to_text_when_cover_cannot_be_sent(self) -> None:
        self.bot.send_photo.side_effect = api_error(400, "Bad Request: wrong file identifier")
        with (
            patch.object(bot_module, "MENU_COVER_FILE_ID", "broken-id"),
            self.assertLogs("showcase-bot", level="ERROR"),
        ):
            bot_module.send_main_menu(202)
        self.bot.send_message.assert_called_once()
        self.assertEqual(self.bot.send_message.call_args.args[1], bot_module.texts.MAIN_MENU)


class TokenMaskTest(unittest.TestCase):
    def test_token_is_removed_from_log_message(self) -> None:
        record = logging.LogRecord(
            "test", logging.ERROR, __file__, 1,
            "Ошибка запроса https://api.telegram.org/bot%s/getUpdates",
            ("123456789:" + "A" * 35,), None,
        )
        logger_module.TokenMaskFilter().filter(record)
        self.assertNotIn("A" * 35, record.getMessage())
        self.assertIn("<TOKEN>", record.getMessage())


if __name__ == "__main__":
    unittest.main()
