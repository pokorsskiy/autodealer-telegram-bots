"""Проверки Web App-бота без подключения к Telegram."""

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SHOWCASE_WEBAPP_BOT_TOKEN", "test-token")
os.environ.setdefault("SHOWCASE_WEB_APP_URL", "https://example.com/webapp")
os.environ.setdefault("SHOWCASE_WEBAPP_DEMO_MODE", "0")

import bot as bot_module
import database as database_module
import logger as logger_module

# Тесты по умолчанию проверяют рабочий бот, демо — отдельным тестом.
bot_module.DEMO_MODE = False


def user_message(raw_data: str) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(id=202),
        from_user=SimpleNamespace(
            id=101,
            first_name="Иван",
            last_name="Петров",
            username="ivan_auto",
        ),
        web_app_data=SimpleNamespace(data=raw_data),
    )


class WebAppBotTest(unittest.TestCase):
    def test_parse_car_lead(self) -> None:
        lead = bot_module._parse_lead(
            """
            {
              "lead_type": "car", "consent": "1",
              "car_id": "bmw-x5-2023",
              "name": "Иван",
              "phone": "+7 999 123-45-67",
              "username": "@ivan",
              "car_interest": "BMW X5 (2023)",
              "purchase_method": "Наличные",
              "comment": "Светлый салон"
            }
            """
        )
        self.assertIsNotNone(lead)
        self.assertEqual(lead["lead_type"], "car")
        self.assertEqual(lead["car_id"], "bmw-x5-2023")

    def test_manager_lead_requires_comment(self) -> None:
        lead = bot_module._parse_lead(
            """
            {
              "lead_type": "manager", "consent": "1",
              "name": "Иван",
              "phone": "+7 999 123-45-67",
              "car_interest": "Нужна помощь с выбором",
              "purchase_method": "Нужна консультация",
              "comment": ""
            }
            """
        )
        self.assertIsNone(lead)

    def test_invalid_phone_is_rejected(self) -> None:
        lead = bot_module._parse_lead(
            """
            {
              "lead_type": "car", "consent": "1",
              "name": "Иван",
              "phone": "123",
              "car_interest": "Toyota Camry",
              "purchase_method": "Кредит"
            }
            """
        )
        self.assertIsNone(lead)

    def test_lead_without_consent_is_rejected(self) -> None:
        lead = bot_module._parse_lead(
            """
            {
              "lead_type": "car",
              "name": "Иван",
              "phone": "+7 999 123-45-67",
              "car_interest": "Toyota Camry",
              "purchase_method": "Кредит"
            }
            """
        )
        self.assertIsNone(lead)

    def test_start_with_prospect_demo_opens_catalog_and_admin(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=202), text="/start acme-test",
            from_user=SimpleNamespace(id=101, first_name="Иван"),
        )
        with tempfile.TemporaryDirectory() as folder:
            demo = Path(folder) / "demos" / "acme-test"
            demo.mkdir(parents=True)
            (demo / "demo.json").write_text('{"brand": "Авто <Импорт>"}', encoding="utf-8")
            with (
                patch.object(bot_module, "BASE_DIR", Path(folder)),
                patch.object(bot_module, "DEMO_MODE", True),
                patch.object(bot_module, "WEB_APP_URL", "https://example.com/"),
                patch.object(bot_module.bot, "send_photo") as send_photo,
            ):
                send_photo.return_value = SimpleNamespace(photo=[])
                bot_module.start(message)

        caption = send_photo.call_args.kwargs["caption"]
        self.assertIn("Авто &lt;Импорт&gt;", caption)
        buttons = [b for row in send_photo.call_args.kwargs["reply_markup"].keyboard for b in row]
        self.assertEqual(
            [b.web_app.url for b in buttons],
            ["https://example.com/?demo=acme-test", "https://example.com/admin/demo?demo=acme-test"],
        )

    def test_start_with_expired_demo_shows_no_buttons(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=202), text="/start acme-test",
            from_user=SimpleNamespace(id=101, first_name="Иван"),
        )
        with tempfile.TemporaryDirectory() as folder:
            demo = Path(folder) / "demos" / "acme-test"
            demo.mkdir(parents=True)
            (demo / "demo.json").write_text(
                '{"brand": "Велма", "expires": "2020-01-01"}', encoding="utf-8"
            )
            with (
                patch.object(bot_module, "BASE_DIR", Path(folder)),
                patch.object(bot_module, "DEMO_MODE", True),
                patch.object(bot_module, "WEB_APP_URL", "https://example.com/"),
                patch.object(bot_module.bot, "send_message") as send_message,
                patch.object(bot_module.bot, "send_photo") as send_photo,
            ):
                bot_module.start(message)

        send_photo.assert_not_called()
        self.assertIn("завершено", send_message.call_args.args[1])
        self.assertNotIn("reply_markup", send_message.call_args.kwargs)

    def test_start_with_unknown_demo_shows_usual_menu(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=202), text="/start ../secret",
            from_user=SimpleNamespace(id=101, first_name="Иван"),
        )
        with (
            patch.object(bot_module, "DEMO_MODE", True),
            patch.object(bot_module, "WEB_APP_URL", "https://example.com/webapp"),
            patch.object(bot_module.bot, "send_photo") as send_photo,
        ):
            send_photo.return_value = SimpleNamespace(photo=[])
            bot_module.start(message)

        buttons = [b for row in send_photo.call_args.kwargs["reply_markup"].keyboard for b in row]
        self.assertEqual([b.text for b in buttons], ["🚗 Открыть Web App"])

    def test_start_has_single_webapp_button(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=202),
            from_user=SimpleNamespace(id=101, first_name="Иван"),
        )
        with (
            patch.object(bot_module, "WEB_APP_URL", "https://example.com/webapp"),
            patch.object(bot_module.bot, "send_photo") as send_photo,
        ):
            send_photo.return_value = SimpleNamespace(photo=[])
            bot_module.start(message)

        markup = send_photo.call_args.kwargs["reply_markup"]
        buttons = [button for row in markup.keyboard for button in row]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].text, "🚗 Открыть Web App")
        self.assertEqual(buttons[0].web_app.url, "https://example.com/webapp")
        self.assertIn("Иван", send_photo.call_args.kwargs["caption"])

    def test_admin_command_only_for_listed_accounts(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=202), from_user=SimpleNamespace(id=555)
        )
        with patch.object(bot_module, "TELEGRAM_ADMINS", {555: "owner"}):
            self.assertTrue(bot_module._is_telegram_admin(message))
            message.from_user.id = 101
            self.assertFalse(bot_module._is_telegram_admin(message))

    def test_admin_command_sends_admin_webapp(self) -> None:
        message = SimpleNamespace(
            chat=SimpleNamespace(id=202), from_user=SimpleNamespace(id=555)
        )
        with (
            patch.object(bot_module, "ADMIN_WEB_APP_URL", "https://example.com/admin/tg"),
            patch.object(bot_module.bot, "send_message") as send_message,
        ):
            bot_module.admin(message)
        button = send_message.call_args.kwargs["reply_markup"].keyboard[0][0]
        self.assertEqual(button.text, "🔐 Открыть админку")
        self.assertEqual(button.web_app.url, "https://example.com/admin/tg")

    def test_valid_lead_is_saved_and_sent_to_manager(self) -> None:
        raw_data = (
            '{"lead_type":"car","consent":"1","car_id":"toyota-camry-2024","name":"Иван",'
            '"phone":"+7 999 123-45-67","username":"@ivan","car_interest":"Toyota Camry",'
            '"purchase_method":"Наличные","comment":""}'
        )
        with (
            patch.object(bot_module, "YOUR_CHAT_ID", 909),
            patch.object(bot_module, "save_lead") as save_lead,
            patch.object(bot_module.bot, "send_message") as send_message,
        ):
            bot_module.handle_webapp_data(user_message(raw_data))

        save_lead.assert_called_once()
        self.assertEqual(send_message.call_args_list[0].args[0], 909)
        self.assertIn("Toyota Camry", send_message.call_args_list[0].args[1])
        self.assertIn("Заявка принята", send_message.call_args_list[1].args[1])

    def test_lead_notice_without_contacts(self) -> None:
        """LEAD_NOTIFY_CONTACTS=0: менеджеру приходит заявка без имени и телефона."""
        raw_data = (
            '{"lead_type":"car","consent":"1","car_id":"toyota-camry-2024","name":"Иван",'
            '"phone":"+7 999 123-45-67","username":"@ivan","car_interest":"Toyota Camry",'
            '"purchase_method":"Наличные","comment":""}'
        )
        with (
            patch.object(bot_module, "YOUR_CHAT_ID", 909),
            patch.object(bot_module, "LEAD_NOTIFY_CONTACTS", False),
            patch.object(bot_module, "ADMIN_WEB_APP_URL", "https://example.com/admin/tg"),
            patch.object(bot_module, "save_lead", return_value=12),
            patch.object(bot_module.bot, "send_message") as send_message,
        ):
            bot_module.handle_webapp_data(user_message(raw_data))

        notice = send_message.call_args_list[0]
        self.assertIn("№12", notice.args[1])
        self.assertIn("Toyota Camry", notice.args[1])
        for secret in ("Иван", "123-45-67", "@ivan"):
            self.assertNotIn(secret, notice.args[1])
        rows = notice.kwargs["reply_markup"].keyboard
        self.assertEqual(rows[1][0].web_app.url, "https://example.com/admin/tg")

    def test_demo_lead_is_not_saved_or_sent(self) -> None:
        raw_data = (
            '{"lead_type":"car","consent":"1","car_id":"toyota-camry-2024","name":"Иван",'
            '"phone":"+7 999 123-45-67","username":"@ivan","car_interest":"Toyota Camry",'
            '"purchase_method":"Наличные","comment":""}'
        )
        with (
            patch.object(bot_module, "DEMO_MODE", True),
            patch.object(bot_module, "YOUR_CHAT_ID", 909),
            patch.object(bot_module, "save_lead") as save_lead,
            patch.object(bot_module.bot, "send_message") as send_message,
        ):
            bot_module.handle_webapp_data(user_message(raw_data))

        save_lead.assert_not_called()
        send_message.assert_called_once()
        self.assertEqual(send_message.call_args.args[0], 202)
        self.assertIn("демо", send_message.call_args.args[1])

    def test_database_migration_preserves_old_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy.db"
            with closing(sqlite3.connect(db_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE webapp_leads (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id INTEGER NOT NULL,
                            username TEXT,
                            name TEXT NOT NULL,
                            phone TEXT NOT NULL,
                            car_interest TEXT NOT NULL,
                            purchase_method TEXT NOT NULL,
                            comment TEXT,
                            created_at TEXT NOT NULL
                        )
                        """
                    )
                    connection.execute(
                        """
                        INSERT INTO webapp_leads (
                            user_id, username, name, phone, car_interest,
                            purchase_method, comment, created_at
                        ) VALUES (1, 'old_user', 'Старый лид', '+79991234567',
                                  'Toyota', 'Наличные', '', '2026-01-01T12:00:00')
                        """
                    )

            with patch.object(database_module, "DB_NAME", str(db_path)):
                database_module.init_db()

            with closing(sqlite3.connect(db_path)) as connection:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(webapp_leads)")
                }
                count = connection.execute("SELECT COUNT(*) FROM webapp_leads").fetchone()[0]

            self.assertTrue({"lead_type", "contact_username", "car_id", "is_archived"} <= columns)
            self.assertEqual(count, 1)
            self.assertTrue(Path(f"{db_path}.bak").exists())

    def test_safe_handler_does_not_send_traceback(self) -> None:
        fake_bot = Mock()

        @logger_module.safe_handler(fake_bot)
        def broken_handler(message: SimpleNamespace) -> None:
            raise RuntimeError("секретные детали")

        with (
            patch.object(logger_module, "YOUR_CHAT_ID", 202),
            patch.object(logger_module.logger, "exception"),
        ):
            broken_handler(SimpleNamespace(chat=SimpleNamespace(id=202)))

        self.assertEqual(fake_bot.send_message.call_count, 1)
        sent_text = fake_bot.send_message.call_args.args[1]
        self.assertNotIn("Traceback", sent_text)
        self.assertNotIn("секретные детали", sent_text)


if __name__ == "__main__":
    unittest.main()
