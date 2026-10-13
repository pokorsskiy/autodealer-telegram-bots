"""Проверки обоих пользовательских сценариев Hybrid-бота без Telegram."""

import hashlib
import hmac
import itertools
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SHOWCASE_HYBRID_BOT_TOKEN", "test-token")
os.environ.setdefault("SHOWCASE_HYBRID_WEB_APP_URL", "https://example.com/webapp")
os.environ.setdefault("SHOWCASE_HYBRID_DEMO_MODE", "0")

import bot as bot_module
import database as database_module
import keyboards as keyboards_module
import logger as logger_module

# Тесты по умолчанию проверяют рабочий бот, демо — отдельным тестом.
bot_module.DEMO_MODE = False


def callback(
    data: str,
    message_id: int = 303,
    content_type: str = "text",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"callback-{data}",
        data=data,
        from_user=SimpleNamespace(id=101, first_name="Иван"),
        message=SimpleNamespace(
            chat=SimpleNamespace(id=202),
            message_id=message_id,
            content_type=content_type,
        ),
    )


def text_message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(
            id=101,
            first_name="Иван",
            last_name="Петров",
            username="ivan_auto",
        ),
        chat=SimpleNamespace(id=202),
    )


def webapp_message(payload: dict[str, str]) -> SimpleNamespace:
    message = text_message("")
    message.web_app_data = SimpleNamespace(data=json.dumps(payload, ensure_ascii=False))
    return message


class HybridBotTest(unittest.TestCase):
    def setUp(self) -> None:
        bot_module.calculator_sessions.clear()

    def test_main_menu_combines_chat_and_webapp_actions(self) -> None:
        with (
            patch.object(keyboards_module, "REVIEWS_URL", "https://t.me/reviews"),
            patch.object(keyboards_module, "COMMUNITY_URL", "https://t.me/chat"),
            patch.object(keyboards_module, "TELEGRAM_CHANNEL_URL", "https://t.me/channel"),
            patch.object(keyboards_module, "VK_URL", "https://vk.com/demo"),
        ):
            labels = [
                button.text
                for row in bot_module.main_menu("https://example.com/webapp").keyboard
                for button in row
            ]
        self.assertEqual(
            labels,
            [
                "🚗 Автомобили в наличии",
                "🧮 Калькулятор",
                "❓ Вопросы",
                "⭐ Отзывы",
                "👥 Чат клиентов",
                "📢 Наш Telegram-канал",
                "🌐 Другие соцсети",
                "✉️ Написать менеджеру",
            ],
        )
        buttons = [
            button
            for row in bot_module.main_menu("https://example.com/webapp").keyboard
            for button in row
        ]
        self.assertEqual(buttons[0].web_app.url, "https://example.com/webapp")
        self.assertEqual(buttons[-1].text, "✉️ Написать менеджеру")

    def test_start_sends_photo_menu(self) -> None:
        with (
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "send_photo") as send_photo,
            patch.object(bot_module.bot, "delete_message") as delete_message,
        ):
            send_message.return_value = SimpleNamespace(message_id=808)
            send_photo.return_value = SimpleNamespace(photo=[])
            bot_module.start(text_message("/start"))

        self.assertIsInstance(
            send_message.call_args.kwargs["reply_markup"],
            bot_module.types.ReplyKeyboardRemove,
        )
        self.assertEqual(
            send_photo.call_args.kwargs["reply_markup"].keyboard[0][0].text,
            "🚗 Автомобили в наличии",
        )
        delete_message.assert_called_once_with(202, 808)

    def test_menu_hides_buttons_without_links(self) -> None:
        """Ненастроенные разделы просто не показываются: заглушек в демо нет."""
        with (
            patch.object(keyboards_module, "MANAGER_URL", ""),
            patch.object(keyboards_module, "REVIEWS_URL", ""),
            patch.object(keyboards_module, "COMMUNITY_URL", ""),
            patch.object(keyboards_module, "TELEGRAM_CHANNEL_URL", ""),
            patch.object(keyboards_module, "MAX_URL", ""),
            patch.object(keyboards_module, "VK_URL", ""),
            patch.object(keyboards_module, "YOUTUBE_URL", ""),
        ):
            labels = [
                button.text
                for row in bot_module.main_menu("").keyboard
                for button in row
            ]
        self.assertEqual(
            labels,
            ["🧮 Калькулятор", "❓ Вопросы", "✉️ Написать менеджеру"],
        )

    def test_manager_button_uses_direct_url_when_configured(self) -> None:
        with patch.object(keyboards_module, "MANAGER_URL", "https://t.me/dealer_auto"):
            buttons = [
                button
                for row in keyboards_module.main_menu("https://example.com/webapp").keyboard
                for button in row
            ]
        manager_button = next(
            button for button in buttons if button.text == "✉️ Написать менеджеру"
        )
        self.assertEqual(manager_button.url, "https://t.me/dealer_auto")

    def test_manager_button_uses_placeholder_without_link(self) -> None:
        with patch.object(keyboards_module, "MANAGER_URL", ""):
            buttons = [
                button
                for row in keyboards_module.main_menu("https://example.com/webapp").keyboard
                for button in row
            ]
        manager_button = next(
            button for button in buttons if button.text == "✉️ Написать менеджеру"
        )
        self.assertEqual(manager_button.callback_data, "manager")

    def test_socials_show_only_configured_links(self) -> None:
        """Раздел соцсетей собирается из заданных ссылок: пустые не показываем."""
        with (
            patch.object(keyboards_module, "MAX_URL", "https://max.ru/demo"),
            patch.object(keyboards_module, "VK_URL", ""),
            patch.object(keyboards_module, "YOUTUBE_URL", ""),
        ):
            labels = [
                button.text
                for row in keyboards_module.socials_menu().keyboard
                for button in row
            ]
        self.assertEqual(labels, ["Канал в MAX", "← Назад в меню"])

    def test_site_command_sends_webapp_button(self) -> None:
        with (
            patch.object(bot_module, "WEB_APP_URL", "https://example.com/webapp"),
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "delete_message"),
        ):
            send_message.side_effect = [SimpleNamespace(message_id=808), None]
            bot_module.site(text_message("/site"))

        markup = send_message.call_args_list[1].kwargs["reply_markup"]
        button = markup.keyboard[0][0]
        self.assertEqual(button.text, "🚗 Открыть Web App")
        self.assertEqual(button.web_app.url, "https://example.com/webapp")

    def test_admin_command_only_for_listed_accounts(self) -> None:
        with patch.object(bot_module, "TELEGRAM_ADMIN_IDS", {101}):
            self.assertTrue(bot_module._is_telegram_admin(text_message("/admin")))
        self.assertFalse(bot_module._is_telegram_admin(text_message("/admin")))

    def test_admin_command_sends_admin_webapp(self) -> None:
        with (
            patch.object(bot_module, "ADMIN_WEB_APP_URL", "https://example.com/admin/tg"),
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "delete_message"),
        ):
            send_message.side_effect = [SimpleNamespace(message_id=808), None]
            bot_module.admin(text_message("/admin"))
        button = send_message.call_args_list[1].kwargs["reply_markup"].keyboard[0][0]
        self.assertEqual(button.text, "🔐 Открыть админку")
        self.assertEqual(button.web_app.url, "https://example.com/admin/tg")

    def test_site_command_is_registered(self) -> None:
        with (
            patch.object(bot_module.bot, "set_my_commands") as set_commands,
            patch.object(bot_module.bot, "set_chat_menu_button"),
        ):
            bot_module.configure_commands()
        commands = set_commands.call_args.args[0]
        self.assertEqual(
            [(command.command, command.description) for command in commands],
            [
                ("start", "Запустить бота"),
                ("menu", "Открыть меню"),
                ("site", "Открыть Web App"),
            ],
        )

    def test_calculator_flow(self) -> None:
        """Итог приходит отдельным сообщением, а меню — следом за ним."""
        message_ids = itertools.count(401)
        with (
            patch.object(bot_module, "WEB_APP_URL", "https://example.com/webapp"),
            patch.object(bot_module.bot, "answer_callback_query"),
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "send_photo") as send_photo,
            patch.object(bot_module.bot, "delete_message") as delete_message,
            patch.object(bot_module.bot, "edit_message_text"),
        ):
            send_message.side_effect = lambda *args, **kwargs: SimpleNamespace(
                message_id=next(message_ids)
            )
            send_photo.return_value = SimpleNamespace(photo=[])
            bot_module.handle_callback(callback("calculator"))
            self.assertEqual(bot_module.calculator_sessions[101]["step"], "mode")
            bot_module.handle_callback(callback("calc:mode:budget", message_id=303))
            bot_module.handle_text(text_message("2 500 000 ₽"))
            panel_id = bot_module.calculator_sessions[101]["message_id"]
            bot_module.handle_callback(callback("calc:age:3_to_5", message_id=panel_id))
            bot_module.handle_text(text_message("2,0 л"))
            result_call = send_message.call_args_list[-2]
            menu_call = send_message.call_args_list[-1]

        self.assertNotIn(101, bot_module.calculator_sessions)
        result_text = result_call.args[1]
        self.assertIn("Что помещается в бюджет", result_text)
        self.assertIn("Автомобиль за границей", result_text)
        self.assertIn("Утилизационный сбор", result_text)
        self.assertIn("Доставка и расходы", result_text)
        self.assertIn("Остаётся", result_text)
        self.assertIn("Цена автомобиля подобрана под ваш бюджет", result_text)
        self.assertIsNone(result_call.kwargs.get("reply_markup"))
        budget_button = menu_call.kwargs["reply_markup"].keyboard[0][0]
        self.assertEqual(budget_button.text, "🚗 Машины в этом бюджете")
        # Каталог фильтруем по бюджету клиента, а не по подобранной цене.
        self.assertIn("max_price=2500000", budget_button.web_app.url)
        # Возраст «от 3 до 5 лет» открывает каталог с годами выпуска «от» и «до».
        current_year = date.today().year
        self.assertIn(f"min_year={current_year - 5}", budget_button.web_app.url)
        self.assertIn(f"max_year={current_year - 3}", budget_button.web_app.url)
        self.assertIn(
            "🧮 Пересчитать",
            [
                button.text
                for row in menu_call.kwargs["reply_markup"].keyboard
                for button in row
            ],
        )
        self.assertIn(
            (202, panel_id),
            [call.args for call in delete_message.call_args_list],
        )
        send_photo.assert_not_called()

    def test_known_price_mode_adds_import_costs(self) -> None:
        """Ветка «знаю цену» считает вперёд: к цене прибавляются расходы."""
        bot_module.calculator_sessions[101] = {
            "step": "engine",
            "price_mode": "known",
            "age": "3_to_5",
            "car_price_rub": 2_500_000,
            "message_id": 404,
        }
        with (
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "delete_message"),
        ):
            send_message.return_value = SimpleNamespace(message_id=505)
            bot_module.handle_text(text_message("2,0 л"))
            result_text = send_message.call_args_list[-2].args[1]

        self.assertIn("Ориентировочный расчёт", result_text)
        self.assertIn("Стоимость автомобиля", result_text)
        self.assertNotIn("бюджет", result_text)

    def test_small_budget_asks_for_another_sum(self) -> None:
        """Если бюджета не хватает даже на привоз, расчёт не выдаём."""
        bot_module.calculator_sessions[101] = {
            "step": "engine",
            "price_mode": "budget",
            "age": "3_to_5",
            "car_price_rub": 500_000,
            "message_id": 404,
        }
        with (
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "delete_message"),
        ):
            send_message.return_value = SimpleNamespace(message_id=505)
            bot_module.handle_text(text_message("2,0 л"))

        self.assertEqual(send_message.call_count, 1)
        self.assertIn("не подобрать", send_message.call_args.args[1])
        self.assertIn(101, bot_module.calculator_sessions)

    def test_result_has_no_catalog_button_without_webapp(self) -> None:
        """Без настроенного Web App кнопку не показываем, а не ведём в пустоту."""
        bot_module.calculator_sessions[101] = {
            "step": "engine",
            "price_mode": "known",
            "age": "3_to_5",
            "car_price_rub": 2_500_000,
            "message_id": 404,
        }
        with (
            patch.object(bot_module, "WEB_APP_URL", ""),
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "send_photo") as send_photo,
            patch.object(bot_module.bot, "delete_message"),
        ):
            send_message.return_value = SimpleNamespace(message_id=505)
            send_photo.return_value = SimpleNamespace(photo=[])
            bot_module.handle_text(text_message("2,0 л"))
            menu_call = send_message.call_args_list[-1]

        self.assertEqual(
            menu_call.kwargs["reply_markup"].keyboard[0][0].text,
            "🧮 Пересчитать",
        )

    def test_calculator_uses_webapp_input_steps(self) -> None:
        bot_module.calculator_sessions[101] = {
            "step": "price",
            "price_mode": "known",
            "message_id": 404,
        }
        with (
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "delete_message"),
            patch.object(bot_module.bot, "edit_message_text"),
        ):
            send_message.return_value = SimpleNamespace(message_id=505)
            bot_module.handle_text(text_message("2 505 000"))
        self.assertEqual(send_message.call_count, 1)
        self.assertEqual(bot_module.calculator_sessions[101]["step"], "age")
        self.assertEqual(bot_module.calculator_sessions[101]["car_price_rub"], 2_510_000)

        bot_module.calculator_sessions[101] = {
            "step": "price",
            "price_mode": "known",
            "message_id": 404,
        }
        with patch.object(bot_module.bot, "send_message") as send_message:
            bot_module.handle_text(text_message("10 000"))
        self.assertEqual(bot_module.calculator_sessions[101]["step"], "price")
        self.assertIn("от 50 000 до 50 000 000", send_message.call_args.args[1])

        bot_module.calculator_sessions[101] = {
            "step": "engine",
            "price_mode": "known",
            "car_price_rub": 2_500_000,
            "age": "3_to_5",
            "message_id": 404,
        }
        with patch.object(bot_module.bot, "send_message") as send_message:
            bot_module.handle_text(text_message("1,65"))
        self.assertEqual(bot_module.calculator_sessions[101]["step"], "engine")
        self.assertIn("шагом 0.1", send_message.call_args.args[1])

    def test_webapp_lead_is_validated_saved_and_notified(self) -> None:
        payload = {
            "lead_type": "car", "consent": "1",
            "car_id": "bmw-x5-2023",
            "name": "Иван",
            "phone": "+7 999 123-45-67",
            "username": "@ivan",
            "car_interest": "BMW X5 (2023)",
            "purchase_method": "Наличные",
            "comment": "Светлый салон",
        }
        with (
            patch.object(bot_module, "YOUR_CHAT_ID", 909),
            patch.object(bot_module, "save_lead") as save_lead,
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module, "_send_lead_to_admin") as send_to_admin,
        ):
            bot_module.handle_webapp_data(webapp_message(payload))

        send_to_admin.assert_called_once()
        self.assertEqual(send_to_admin.call_args.args[1]["car_interest"], "BMW X5 (2023)")
        save_lead.assert_called_once_with(
            101,
            "ivan_auto",
            "webapp_car",
            "BMW X5 (2023)",
            "+7 999 123-45-67",
        )
        self.assertIn(
            "Источник:</b> Web App",
            send_message.call_args_list[0].args[1],
        )
        self.assertIn("Заявка из Web App принята", send_message.call_args_list[1].args[1])

    def test_webapp_lead_notice_without_contacts(self) -> None:
        """LEAD_NOTIFY_CONTACTS=0: менеджеру приходит заявка без имени и телефона."""
        payload = {
            "lead_type": "car", "consent": "1", "car_id": "bmw-x5-2023", "name": "Иван",
            "phone": "+7 999 123-45-67", "username": "@ivan",
            "car_interest": "BMW X5 (2023)", "purchase_method": "Наличные", "comment": "",
        }
        with (
            patch.object(bot_module, "YOUR_CHAT_ID", 909),
            patch.object(bot_module, "LEAD_NOTIFY_CONTACTS", False),
            patch.object(bot_module, "ADMIN_WEB_APP_URL", "https://example.com/admin/tg"),
            patch.object(bot_module, "save_lead"),
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module, "_send_lead_to_admin"),
        ):
            bot_module.handle_webapp_data(webapp_message(payload))

        notice = send_message.call_args_list[0]
        self.assertEqual(notice.args[0], 909)
        self.assertIn("BMW X5 (2023)", notice.args[1])
        for secret in ("Иван", "123-45-67", "@ivan", "ivan_auto"):
            self.assertNotIn(secret, notice.args[1])
        self.assertEqual(
            notice.kwargs["reply_markup"].keyboard[0][0].web_app.url,
            "https://example.com/admin/tg",
        )

    def test_demo_webapp_lead_is_not_saved_or_sent(self) -> None:
        payload = {
            "lead_type": "car", "consent": "1", "car_id": "bmw-x5-2023", "name": "Иван",
            "phone": "+7 999 123-45-67", "username": "@ivan",
            "car_interest": "BMW X5 (2023)", "purchase_method": "Наличные", "comment": "",
        }
        with (
            patch.object(bot_module, "DEMO_MODE", True),
            patch.object(bot_module, "YOUR_CHAT_ID", 909),
            patch.object(bot_module, "save_lead") as save_lead,
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module, "_send_lead_to_admin") as send_to_admin,
        ):
            bot_module.handle_webapp_data(webapp_message(payload))

        save_lead.assert_not_called()
        send_to_admin.assert_not_called()
        send_message.assert_called_once()
        self.assertEqual(send_message.call_args.args[0], 202)
        self.assertIn("демо", send_message.call_args.args[1])

    def test_lead_goes_to_admin_signed_with_bot_token(self) -> None:
        user = SimpleNamespace(id=101, username="ivan_auto")
        lead = {"name": "Иван", "phone": "+7 999 123-45-67", "car_interest": "BMW X5"}
        with (
            patch.object(bot_module, "ADMIN_LEADS_URL", "https://example.com/api/bot/leads"),
            patch.object(bot_module, "TOKEN", "222:hybrid-token"),
            patch.object(bot_module.requests, "post") as post,
        ):
            bot_module._send_lead_to_admin(user, lead)

        body = post.call_args.kwargs["data"]
        expected = hmac.new(b"222:hybrid-token", body, hashlib.sha256).hexdigest()
        self.assertEqual(post.call_args.kwargs["headers"]["X-Bot-Signature"], expected)
        sent = json.loads(body)
        # Витрина принимает копию заявки только с отметкой согласия.
        self.assertEqual(
            (sent["user_id"], sent["username"], sent["lead"]),
            (101, "ivan_auto", {**lead, "consent": "1"}),
        )

    def test_admin_unavailable_does_not_break_lead(self) -> None:
        with (
            patch.object(bot_module, "ADMIN_LEADS_URL", "https://example.com/api/bot/leads"),
            patch.object(bot_module.requests, "post", side_effect=bot_module.RequestException),
            patch.object(bot_module.logger, "exception") as log,
        ):
            bot_module._send_lead_to_admin(SimpleNamespace(id=1, username=None), {})
        log.assert_called_once()

    def test_invalid_webapp_phone_is_rejected(self) -> None:
        payload = {
            "lead_type": "car", "consent": "1",
            "name": "Иван",
            "phone": "123",
            "car_interest": "BMW X5",
            "purchase_method": "Наличные",
        }
        with (
            patch.object(bot_module, "save_lead") as save_lead,
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module, "_send_lead_to_admin") as send_to_admin,
        ):
            bot_module.handle_webapp_data(webapp_message(payload))
        save_lead.assert_not_called()
        send_to_admin.assert_not_called()
        self.assertIn("Не удалось прочитать заявку", send_message.call_args.args[1])

    def test_webapp_lead_without_consent_is_rejected(self) -> None:
        """Без согласия на обработку персональных данных заявку не сохраняем."""
        payload = {
            "lead_type": "car",
            "name": "Иван",
            "phone": "+7 999 123-45-67",
            "car_interest": "BMW X5",
            "purchase_method": "Наличные",
        }
        with (
            patch.object(bot_module, "save_lead") as save_lead,
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module, "_send_lead_to_admin") as send_to_admin,
        ):
            bot_module.handle_webapp_data(webapp_message(payload))
        save_lead.assert_not_called()
        send_to_admin.assert_not_called()
        self.assertIn("Не удалось прочитать заявку", send_message.call_args.args[1])

    def test_old_database_gets_consent_column_and_keeps_leads(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_name = str(Path(folder) / "leads.db")
            with closing(sqlite3.connect(db_name)) as connection:
                with connection:
                    connection.execute(
                        "CREATE TABLE hybrid_leads (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "user_id INTEGER NOT NULL, username TEXT, lead_type TEXT NOT NULL, "
                        "car_interest TEXT, phone TEXT, created_at TEXT NOT NULL)"
                    )
                    connection.execute(
                        "INSERT INTO hybrid_leads (user_id, lead_type, created_at) "
                        "VALUES (1, 'webapp_car', '2026-10-01T10:00:00')"
                    )
            with patch.object(database_module, "DB_NAME", db_name):
                database_module.init_db()
                database_module.save_lead(2, None, "webapp_car", "BMW X5", "+79990000000")
            with closing(sqlite3.connect(db_name)) as connection:
                rows = connection.execute(
                    "SELECT user_id, consent_at FROM hybrid_leads ORDER BY id"
                ).fetchall()
            self.assertEqual(rows[0], (1, ""))
            self.assertEqual(rows[1][0], 2)
            self.assertTrue(rows[1][1])
            self.assertEqual(len(list(Path(folder).glob("leads.db.bak.*"))), 1)

    def test_safe_handler_does_not_send_exception_details(self) -> None:
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
