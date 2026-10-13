"""Проверка основного пользовательского сценария без подключения к Telegram."""

import itertools
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("SHOWCASE_TELEGRAM_DEMO_MODE", "0")

import bot as bot_module
import keyboards as keyboards_module
import logger as logger_module


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
        from_user=SimpleNamespace(id=101, first_name="Иван"),
        chat=SimpleNamespace(id=202),
    )


class TelegramShowcaseFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        bot_module.calculator_sessions.clear()
        bot_module.order_sessions.clear()
        bot_module.last_calculations.clear()

    def test_main_menu_sections(self) -> None:
        with (
            patch.object(keyboards_module, "REVIEWS_URL", "https://t.me/reviews"),
            patch.object(keyboards_module, "COMMUNITY_URL", "https://t.me/chat"),
            patch.object(keyboards_module, "TELEGRAM_CHANNEL_URL", "https://t.me/channel"),
            patch.object(keyboards_module, "VK_URL", "https://vk.com/demo"),
            patch.object(keyboards_module, "MANAGER_URL", "https://t.me/manager"),
        ):
            labels = [
                button.text
                for row in bot_module.main_menu().keyboard
                for button in row
            ]
        self.assertEqual(
            labels,
            [
                "🧮 Калькулятор",
                "❓ Вопросы",
                "⭐ Отзывы",
                "👥 Чат клиентов",
                "📢 Наш Telegram-канал",
                "🌐 Другие соцсети",
                "🟠 Заказать автомобиль",
                "✉️ Написать менеджеру",
            ],
        )

    def test_menu_hides_sections_without_links(self) -> None:
        """Ненастроенные разделы просто не показываются: заглушек в демо нет."""
        with (
            patch.object(keyboards_module, "REVIEWS_URL", ""),
            patch.object(keyboards_module, "COMMUNITY_URL", ""),
            patch.object(keyboards_module, "TELEGRAM_CHANNEL_URL", ""),
            patch.object(keyboards_module, "MAX_URL", ""),
            patch.object(keyboards_module, "VK_URL", ""),
            patch.object(keyboards_module, "YOUTUBE_URL", ""),
            patch.object(keyboards_module, "MANAGER_URL", ""),
        ):
            labels = [
                button.text
                for row in bot_module.main_menu().keyboard
                for button in row
            ]
        self.assertEqual(
            labels,
            ["🧮 Калькулятор", "❓ Вопросы", "🟠 Заказать автомобиль"],
        )

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

    def test_only_start_command_is_configured(self) -> None:
        with (
            patch.object(bot_module.bot, "set_my_commands") as set_commands,
            patch.object(bot_module.bot, "set_chat_menu_button") as set_menu_button,
        ):
            bot_module.configure_commands()
        commands = set_commands.call_args.args[0]
        described = [(command.command, command.description) for command in commands]
        self.assertEqual(described, [("start", "Запустить бота")])
        self.assertIsInstance(
            set_menu_button.call_args.kwargs["menu_button"],
            bot_module.types.MenuButtonCommands,
        )

    def test_calculator_parses_rubles_and_liters(self) -> None:
        self.assertEqual(bot_module._parse_rub_price("2 500 000 ₽"), 2_500_000)
        self.assertEqual(bot_module._parse_rub_price("2\xa0500\xa0000 руб."), 2_500_000)
        self.assertEqual(bot_module._parse_engine_liters("1,6 л"), 1.6)
        self.assertEqual(bot_module._parse_engine_liters("2.0 литра"), 2.0)

    def test_calculator_flow(self) -> None:
        """Панель расчёта держится внизу чата, итог остаётся отдельным сообщением."""
        message_ids = itertools.count(401)
        with (
            patch.object(bot_module.bot, "answer_callback_query"),
            patch.object(bot_module.bot, "edit_message_text") as edit_message,
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "send_photo") as send_photo,
            patch.object(bot_module.bot, "delete_message") as delete_message,
        ):
            send_message.side_effect = lambda *args, **kwargs: SimpleNamespace(
                message_id=next(message_ids)
            )
            send_photo.return_value = SimpleNamespace(photo=[])
            bot_module.start(text_message("/start"))
            self.assertIsInstance(
                send_message.call_args_list[0].kwargs["reply_markup"],
                bot_module.types.ReplyKeyboardRemove,
            )
            self.assertEqual(
                send_photo.call_args.kwargs["reply_markup"].keyboard[0][0].text,
                "🧮 Калькулятор",
            )
            delete_message.assert_called_once_with(202, 401)
            edit_message.assert_not_called()

            bot_module.handle_callback(callback("calculator", content_type="photo"))
            self.assertEqual(bot_module.calculator_sessions[101]["step"], "mode")
            panel_id = bot_module.calculator_sessions[101]["message_id"]
            edit_message.assert_not_called()

            bot_module.handle_callback(callback("calc:mode:known", message_id=panel_id))
            self.assertEqual(bot_module.calculator_sessions[101]["step"], "price")

            bot_module.handle_text(text_message("2 500 000 ₽"))
            self.assertEqual(bot_module.calculator_sessions[101]["step"], "age")
            moved_panel_id = bot_module.calculator_sessions[101]["message_id"]
            self.assertNotEqual(moved_panel_id, panel_id)
            self.assertIn((202, panel_id), [call.args for call in delete_message.call_args_list])
            self.assertEqual(
                send_message.call_args.kwargs["reply_markup"].keyboard[0][0].text,
                "До 3 лет",
            )

            bot_module.handle_callback(callback("calc:age:3_to_5", message_id=moved_panel_id))
            self.assertEqual(bot_module.calculator_sessions[101]["step"], "engine")

            bot_module.handle_text(text_message("2,0 л"))
            result_call = send_message.call_args_list[-2]
            menu_call = send_message.call_args_list[-1]

        self.assertNotIn(101, bot_module.calculator_sessions)
        result_text = result_call.args[1]
        self.assertIn("Итого", result_text)
        self.assertIn("Утилизационный сбор", result_text)
        self.assertIn("2.0 л (2 000 см³)", result_text)
        self.assertIsNone(result_call.kwargs.get("reply_markup"))
        self.assertIn(
            (202, moved_panel_id),
            [call.args for call in delete_message.call_args_list],
        )
        self.assertEqual(send_photo.call_count, 1)
        self.assertEqual(
            [
                button.text
                for row in menu_call.kwargs["reply_markup"].keyboard
                for button in row
            ],
            ["🧮 Пересчитать", "🟠 Заказать автомобиль", "← В меню"],
        )
        self.assertIn("Итого", bot_module.last_calculations[101])

    def test_budget_mode_picks_car_price(self) -> None:
        """Ветка «знаю бюджет» считает назад: подбирает цену под сумму."""
        bot_module.calculator_sessions[101] = {
            "step": "engine",
            "price_mode": "budget",
            "age": "3_to_5",
            "car_price_rub": 4_000_000,
            "message_id": 404,
        }
        with (
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "delete_message"),
        ):
            send_message.return_value = SimpleNamespace(message_id=505)
            bot_module.handle_text(text_message("2,0 л"))
            result_text = send_message.call_args_list[-2].args[1]

        self.assertIn("Что помещается в бюджет", result_text)
        self.assertIn("Автомобиль за границей", result_text)
        self.assertIn("Остаётся", result_text)
        self.assertNotIn(101, bot_module.calculator_sessions)

    def test_small_budget_asks_for_another_sum(self) -> None:
        """Если бюджета не хватает даже на привоз, расчёт не выдаём."""
        bot_module.calculator_sessions[101] = {
            "step": "engine",
            "price_mode": "budget",
            "age": "3_to_5",
            "car_price_rub": 300_000,
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

    def test_cancel_removes_calculator_and_returns_to_menu(self) -> None:
        """Отмена расчёта не оставляет пустой чат, а показывает меню заново."""
        bot_module.calculator_sessions[101] = {"step": "price", "message_id": 505}
        with (
            patch.object(bot_module.bot, "answer_callback_query"),
            patch.object(bot_module.bot, "delete_message") as delete_message,
            patch.object(bot_module.bot, "edit_message_text") as edit_message,
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "send_photo") as send_photo,
        ):
            send_message.return_value = SimpleNamespace(message_id=707)
            send_photo.return_value = SimpleNamespace(photo=[])
            bot_module.handle_callback(callback("calc:cancel", message_id=505))

        self.assertIn((202, 505), [call.args for call in delete_message.call_args_list])
        edit_message.assert_not_called()
        send_photo.assert_called_once()
        self.assertNotIn(101, bot_module.calculator_sessions)

    def test_order_collects_request_and_sends_it_to_manager(self) -> None:
        bot_module.last_calculations[101] = "Итого: 3 000 000 ₽"
        with (
            patch.object(bot_module, "DEMO_MODE", False),
            patch.object(bot_module, "YOUR_CHAT_ID", 909),
            patch.object(bot_module.bot, "answer_callback_query"),
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "delete_message") as delete_message,
        ):
            send_message.side_effect = (SimpleNamespace(message_id=606), None, None)
            bot_module.handle_callback(callback("order", content_type="photo"))
            self.assertEqual(bot_module.order_sessions[101]["message_id"], 606)
            self.assertIn("какой автомобиль", send_message.call_args.args[1])
            bot_module.handle_text(text_message("Нужен BMW X5 до 6 000 000 ₽"))

        self.assertEqual(send_message.call_count, 3)
        self.assertEqual(send_message.call_args_list[1].args[0], 909)
        self.assertIn("Новая заявка", send_message.call_args_list[1].args[1])
        self.assertIn("BMW X5", send_message.call_args_list[1].args[1])
        self.assertIn("Итого: 3 000 000 ₽", send_message.call_args_list[1].args[1])
        self.assertIn("Заявка отправлена", send_message.call_args_list[2].args[1])
        self.assertEqual(
            send_message.call_args_list[2].kwargs["reply_markup"].keyboard[0][0].callback_data,
            "order:menu",
        )
        self.assertEqual(delete_message.call_count, 2)
        delete_message.assert_any_call(202, 303)
        delete_message.assert_any_call(202, 606)
        self.assertNotIn(101, bot_module.order_sessions)

    def test_demo_order_sends_nothing_and_shows_sample(self) -> None:
        bot_module.last_calculations[101] = "Итого: 3 000 000 ₽"
        with (
            patch.object(bot_module, "DEMO_MODE", True),
            patch.object(bot_module, "YOUR_CHAT_ID", 909),
            patch.object(bot_module.bot, "answer_callback_query"),
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "delete_message"),
        ):
            send_message.side_effect = (SimpleNamespace(message_id=606), None, None)
            bot_module.handle_callback(callback("order", content_type="photo"))
            self.assertIn("Это демо", send_message.call_args.args[1])
            bot_module.handle_text(text_message("Нужен BMW X5, мой телефон +7 900 111-22-33"))

        recipients = [call.args[0] for call in send_message.call_args_list]
        self.assertNotIn(909, recipients)
        sample = send_message.call_args_list[1].args[1]
        self.assertIn("Иван Петров", sample)
        self.assertIn("Итого: 3 000 000 ₽", sample)
        self.assertNotIn("BMW X5", sample)
        self.assertNotIn("111-22-33", sample)
        self.assertEqual(
            send_message.call_args_list[2].kwargs["reply_markup"].keyboard[0][0].callback_data,
            "order:menu",
        )
        self.assertNotIn(101, bot_module.order_sessions)

    def test_order_confirmation_sends_new_menu_and_removes_button(self) -> None:
        with (
            patch.object(bot_module.bot, "answer_callback_query"),
            patch.object(bot_module.bot, "edit_message_text") as edit_message,
            patch.object(bot_module.bot, "send_message") as send_message,
            patch.object(bot_module.bot, "send_photo") as send_photo,
            patch.object(bot_module.bot, "delete_message") as delete_message,
        ):
            send_message.return_value = SimpleNamespace(message_id=707)
            send_photo.return_value = SimpleNamespace(photo=[])
            bot_module.handle_callback(callback("order:menu", message_id=606))

        self.assertEqual(edit_message.call_args.kwargs["reply_markup"], None)
        self.assertEqual(edit_message.call_args.kwargs["message_id"], 606)
        self.assertEqual(
            send_photo.call_args.kwargs["reply_markup"].keyboard[0][0].text,
            "🧮 Калькулятор",
        )
        delete_message.assert_called_once_with(202, 707)

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
