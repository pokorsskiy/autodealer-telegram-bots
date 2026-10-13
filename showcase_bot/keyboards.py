"""Клавиатуры бота-витрины."""

from telebot import types

from config import ADMIN_DEMO_URL, REPO_URL, SHOWCASES


def _menu_button(title: str = "← В меню") -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(title, callback_data="menu")


def _showcase_buttons() -> list[types.InlineKeyboardButton]:
    return [
        types.InlineKeyboardButton(item["title"], callback_data=f"showcase:{item['key']}")
        for item in SHOWCASES
    ]


def get_main_keyboard() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🤖 Примеры ботов", callback_data="catalog"),
        types.InlineKeyboardButton("⚙️ Как это сделано", callback_data="about"),
    )
    if REPO_URL:
        markup.add(types.InlineKeyboardButton("💻 Исходный код", url=REPO_URL))
    return markup


def get_catalog_keyboard() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(*_showcase_buttons(), _menu_button())
    return markup


def get_about_keyboard() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🤖 Примеры ботов", callback_data="catalog"))
    if REPO_URL:
        markup.add(types.InlineKeyboardButton("💻 Исходный код", url=REPO_URL))
    markup.add(_menu_button())
    return markup


def get_showcase_keyboard(showcase: dict) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    if showcase["url"]:
        markup.add(types.InlineKeyboardButton("▶️ Открыть бота", url=showcase["url"]))
    if showcase.get("has_admin") and ADMIN_DEMO_URL:
        # Открывается внутри Telegram как мини-приложение, а не в браузере.
        markup.add(
            types.InlineKeyboardButton(
                "🔐 Попробовать админку", web_app=types.WebAppInfo(url=ADMIN_DEMO_URL)
            )
        )
    markup.add(
        types.InlineKeyboardButton("← К примерам", callback_data="catalog"),
        _menu_button("В меню"),
    )
    return markup
