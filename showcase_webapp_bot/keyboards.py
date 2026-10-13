"""Inline-клавиатура открытия Web App."""

from telebot import types


def webapp_keyboard(url: str) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🚗 Открыть Web App",
            web_app=types.WebAppInfo(url=url),
        )
    )
    return markup


def prospect_demo_keyboard(catalog_url: str, admin_url: str) -> types.InlineKeyboardMarkup:
    """Демо под перегонщика: его каталог и админка-песочница, обе внутри Telegram."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🚗 Открыть каталог", web_app=types.WebAppInfo(url=catalog_url)),
        types.InlineKeyboardButton("🔐 Попробовать админку", web_app=types.WebAppInfo(url=admin_url)),
    )
    return markup


def admin_keyboard(url: str) -> types.InlineKeyboardMarkup:
    """Админка открывается внутри Telegram и входит по аккаунту без пароля."""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🔐 Открыть админку",
            web_app=types.WebAppInfo(url=url),
        )
    )
    return markup


def take_lead_keyboard(
    lead_id: int, admin_url: str = "", private_chat: bool = True
) -> types.InlineKeyboardMarkup:
    """Кнопка под уведомлением владельцу: заявка берётся в работу из чата.

    С admin_url добавляется кнопка админки: Web App-кнопки Telegram разрешает
    только в личном чате, в группе админка открывается ссылкой.
    """
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "Взял в работу", callback_data=f"lead:take:{lead_id}"
        )
    )
    if admin_url:
        markup.add(
            types.InlineKeyboardButton("🔐 Открыть админку", web_app=types.WebAppInfo(url=admin_url))
            if private_chat
            else types.InlineKeyboardButton("🔐 Открыть админку", url=admin_url.removesuffix("/tg"))
        )
    return markup
