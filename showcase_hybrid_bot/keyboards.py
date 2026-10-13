"""Клавиатуры Telegram-части гибридного бота."""

from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


def _webapp_button(text: str, web_app_url: str) -> types.InlineKeyboardButton | None:
    if web_app_url.startswith("https://"):
        return types.InlineKeyboardButton(text, web_app=types.WebAppInfo(web_app_url))
    return None


def has_socials() -> bool:
    return any((MAX_URL, VK_URL, YOUTUBE_URL))


def _manager_button() -> types.InlineKeyboardButton:
    """Без ссылки на менеджера ведём на экран с заявкой через каталог."""
    if MANAGER_URL:
        return types.InlineKeyboardButton("✉️ Написать менеджеру", url=MANAGER_URL)
    return types.InlineKeyboardButton("✉️ Написать менеджеру", callback_data="manager")


def main_menu(web_app_url: str) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=2)
    catalog_button = _webapp_button("🚗 Автомобили в наличии", web_app_url)
    if catalog_button:
        markup.add(catalog_button)

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
    markup.add(_manager_button())
    return markup


def admin_keyboard(url: str) -> types.InlineKeyboardMarkup:
    """Админка открывается внутри Telegram и входит по аккаунту без пароля."""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔐 Открыть админку", web_app=types.WebAppInfo(url)))
    return markup


def webapp_keyboard(web_app_url: str) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    button = _webapp_button("🚗 Открыть Web App", web_app_url)
    if button:
        markup.add(button)
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


def manager_menu(web_app_url: str) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    catalog_button = _webapp_button("🚗 Открыть каталог и оставить заявку", web_app_url)
    if catalog_button:
        markup.add(catalog_button)
    markup.add(types.InlineKeyboardButton("← Назад в меню", callback_data="menu"))
    return markup


def calculator_mode_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "Знаю стоимость автомобиля",
            callback_data="calc:mode:known",
        ),
        types.InlineKeyboardButton(
            "Знаю только свой бюджет",
            callback_data="calc:mode:budget",
        ),
        types.InlineKeyboardButton("Отменить расчёт", callback_data="calc:cancel"),
    )
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


# Возраст из калькулятора в годах выпуска: сколько лет назад «от» и «до».
# Обе границы включены: машина пограничного года попадает в ту или другую
# группу в зависимости от месяца выпуска.
AGE_YEARS_BACK = {
    "under_3": (3, None),
    "3_to_5": (5, 3),
    "over_5": (None, 5),
}


def budget_url(web_app_url: str, budget_rub: int, age: str = "") -> str:
    """Добавляет бюджет и годы выпуска в адрес витрины, чтобы каталог открылся с фильтрами."""
    if not web_app_url:
        return ""
    parts = urlsplit(web_app_url)
    query = dict(parse_qsl(parts.query))
    query["max_price"] = str(budget_rub)
    years_from, years_to = AGE_YEARS_BACK.get(age, (None, None))
    current_year = date.today().year
    if years_from is not None:
        query["min_year"] = str(current_year - years_from)
    if years_to is not None:
        query["max_year"] = str(current_year - years_to)
    return urlunsplit(parts._replace(query=urlencode(query)))


def calculation_menu(
    web_app_url: str, budget_rub: int, age: str = ""
) -> types.InlineKeyboardMarkup:
    """Меню после расчёта: пересчитать, посмотреть машины или написать менеджеру."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    catalog_button = _webapp_button(
        "🚗 Машины в этом бюджете",
        budget_url(web_app_url, budget_rub, age),
    )
    if catalog_button:
        markup.add(catalog_button)
    markup.add(
        types.InlineKeyboardButton("🧮 Пересчитать", callback_data="calculator"),
        _manager_button(),
        types.InlineKeyboardButton("← В меню", callback_data="menu"),
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
