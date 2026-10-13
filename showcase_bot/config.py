"""Настройки бота-витрины из окружения и локального .env."""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent


def load_dotenv_file(filepath: Path = PROJECT_DIR / ".env") -> None:
    """Загружает простые пары KEY=VALUE, не перезаписывая окружение."""
    if not filepath.exists():
        return

    for raw_line in filepath.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip("'\""))


load_dotenv_file()


def normalize_telegram_url(value: str) -> str:
    """Преобразует @username и адрес t.me в допустимый URL для кнопки."""
    url = value.strip()
    if url.startswith("@"):
        return f"https://t.me/{url[1:]}"
    if url.startswith(("t.me/", "telegram.me/")):
        return f"https://{url}"
    if url.startswith(("https://", "http://")):
        return url
    return ""


def https_url(value: str) -> str:
    """Кнопка-ссылка и Web App принимают только полный https-адрес."""
    url = value.strip()
    return url if url.startswith("https://") else ""


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MENU_COVER_FILE_ID = os.getenv("MENU_COVER_FILE_ID", "")
# Репозиторий проекта для кнопки «Исходный код». Пустой — кнопки нет.
REPO_URL = https_url(os.getenv("REPO_URL", ""))
# Демо-админка Web App, которую можно попробовать без входа. Пустая — кнопки нет.
ADMIN_DEMO_URL = https_url(os.getenv("ADMIN_DEMO_URL", ""))

# Карточки примеров. video — file_id ролика из лога витрины; пустой — карточка без видео.
SHOWCASES = (
    {
        "key": "basic",
        "title": "Telegram-каталог",
        "tagline": "Расчёт привоза, ответы на вопросы и переход к менеджеру — всё в переписке.",
        "features": (
            "Калькулятор стоимости привоза: пошлина по ставкам ЕАЭС, утильсбор, доставка",
            "Расчёт от цены машины и обратный — от бюджета покупателя",
            "Ответы на частые вопросы, отзывы и ссылки на соцсети",
            "Заявка менеджеру с последним расчётом",
        ),
        "inside": (
            "Сценарии с состоянием в памяти: один экран редактируется, чат не засоряется",
            "Формула вынесена из обработчиков и покрыта тестами",
        ),
        "url": normalize_telegram_url(os.getenv("TELEGRAM_SHOWCASE_URL", "")),
        "video": os.getenv("TELEGRAM_SHOWCASE_VIDEO_ID", ""),
    },
    {
        "key": "webapp",
        "title": "Web App-каталог",
        "tagline": "Витрина автомобилей внутри Telegram и закрытая админка для сотрудников.",
        "features": (
            "Каталог с фото, фильтрами, сортировкой, сравнением и избранным",
            "Заявка с выбранной машиной и согласием на обработку данных",
            "Админка: машины, фото, цены, заявки со статусами, сотрудники, журнал действий",
            "Вход в админку из Telegram без пароля",
        ),
        "inside": (
            "Flask и SQLite: REST API, роли, CSRF, ограничение частоты запросов",
            "Проверка подписи данных Telegram (HMAC-SHA256) для входа и заявок",
            "Миграции схемы без потери данных и резервная копия перед ними",
        ),
        "url": normalize_telegram_url(os.getenv("WEBAPP_SHOWCASE_URL", "")),
        "has_admin": True,
        "video": os.getenv("WEBAPP_SHOWCASE_VIDEO_ID", ""),
    },
    {
        "key": "hybrid",
        "title": "Гибридный бот",
        "tagline": "Быстрые вопросы решаются в чате, подробный подбор — в витрине.",
        "features": (
            "Калькулятор и ответы на вопросы прямо в переписке",
            "Каталог с фильтрами открывается внутри Telegram",
            "Бюджет и годы выпуска из расчёта передаются в фильтры каталога",
            "Заявки из чата и из витрины собираются в одной админке",
        ),
        "inside": (
            "Два сервиса общаются по HTTP: заявка подписывается токеном бота",
            "Админка Web App-бота принимает вход из второго бота",
        ),
        "url": normalize_telegram_url(os.getenv("HYBRID_SHOWCASE_URL", "")),
        "has_admin": True,
        "video": os.getenv("HYBRID_SHOWCASE_VIDEO_ID", ""),
    },
)
