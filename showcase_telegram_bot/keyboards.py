"""Inline-клавиатуры демонстрационного Telegram-бота."""

from telebot import types

from config import (
    COMMUNITY_URL,
    MANAGER_URL,
    MAX_URL,
    REVIEWS_URL,
    TELEGRAM_CHANNEL_URL,
    VK_URL,
    YOUTUBE_URL,
)


def _url_button(text: str, url: str) -> types.InlineKeyboardButton | None:
    """Ненастроенная ссылка означает, что кнопки не будет: заглушек в демо нет."""
    return types.InlineKeyboardButton(text, url=url) if url else None


def has_socials() -> bool:
    return any((MAX_URL, VK_URL, YOUTUBE_URL))


def main_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)
    paired = [
        types.InlineKeyboardButton("🧮 Калькулятор", callback_data="calculator"),
        types.InlineKeyboardButton("❓ Вопросы", callback_data="faq"),
        _url_button("⭐ Отзывы", REVIEWS_URL),
        _url_button("👥 Чат клиентов", COMMUNITY_URL),
    ]
    markup.add(*[button for button in paired if button])

    channel_button = _url_button("📢 Наш Telegram-канал", TELEGRAM_CHANNEL_URL)
    if channel_button:
        markup.add(channel_button)

    if has_socials():
        markup.add(
            types.InlineKeyboardButton("🌐 Другие соцсети", callback_data="socials")
        )
    markup.add(
        types.InlineKeyboardButton("🟠 Заказать автомобиль", callback_data="order")
    )
    manager_button = _url_button("✉️ Написать менеджеру", MANAGER_URL)
    if manager_button:
        markup.add(manager_button)
    return markup


def calculation_menu() -> types.InlineKeyboardMarkup:
    """Меню после расчёта: пересчитать или сразу оставить заявку."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🧮 Пересчитать", callback_data="calculator"),
        types.InlineKeyboardButton("🟠 Заказать автомобиль", callback_data="order"),
        types.InlineKeyboardButton("← В меню", callback_data="menu"),
    )
    return markup


def calculator_mode_menu() -> types.InlineKeyboardMarkup:
    """Первый шаг расчёта: от цены автомобиля или от бюджета клиента."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "Знаю стоимость автомобиля", callback_data="calc:mode:known"
        ),
        types.InlineKeyboardButton(
            "Знаю только свой бюджет", callback_data="calc:mode:budget"
        ),
        types.InlineKeyboardButton("Отменить расчёт", callback_data="calc:cancel"),
    )
    return markup


def calculator_cancel() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("← Отменить расчёт", callback_data="calc:cancel"))
    return markup


def calculator_expired() -> types.InlineKeyboardMarkup:
    """Из устаревшего расчёта даём начать новый, а не только уйти в меню."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🧮 Новый расчёт", callback_data="calculator"),
        types.InlineKeyboardButton("← Назад в меню", callback_data="menu"),
    )
    return markup


def order_cancel() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("← Отменить заявку", callback_data="order:cancel"))
    return markup


def order_confirmation_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("В меню", callback_data="order:menu"))
    return markup


def age_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("До 3 лет", callback_data="calc:age:under_3"),
        types.InlineKeyboardButton("От 3 до 5 лет", callback_data="calc:age:3_to_5"),
        types.InlineKeyboardButton("Старше 5 лет", callback_data="calc:age:over_5"),
        types.InlineKeyboardButton("← Назад в меню", callback_data="menu"),
    )
    return markup


def faq_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Как проходит покупка?", callback_data="faq:purchase"),
        types.InlineKeyboardButton("Сколько занимает доставка?", callback_data="faq:delivery"),
        types.InlineKeyboardButton("Что входит в расчёт?", callback_data="faq:calculation"),
        types.InlineKeyboardButton("Какие нужны документы?", callback_data="faq:documents"),
        types.InlineKeyboardButton("← Назад в меню", callback_data="menu"),
    )
    return markup


def faq_answer_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("← К вопросам", callback_data="faq"),
        types.InlineKeyboardButton("В меню", callback_data="menu"),
    )
    return markup


def socials_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    for button in (
        _url_button("Канал в MAX", MAX_URL),
        _url_button("ВКонтакте", VK_URL),
        _url_button("YouTube", YOUTUBE_URL),
    ):
        if button:
            markup.add(button)
    markup.add(types.InlineKeyboardButton("← Назад в меню", callback_data="menu"))
    return markup
