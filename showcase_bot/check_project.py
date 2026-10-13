"""Быстрая проверка структуры бота-витрины без подключения к Telegram."""

from pathlib import Path

from config import SHOWCASES

REQUIRED_FILES = (
    "bot.py",
    "config.py",
    "keyboards.py",
    "logger.py",
    "texts.py",
    ".env.example",
    "menu-cover.jpg",
)


def main() -> None:
    project_dir = Path(__file__).resolve().parent
    missing = [name for name in REQUIRED_FILES if not (project_dir / name).is_file()]
    if missing:
        raise SystemExit(f"Не найдены файлы: {', '.join(missing)}")
    without_link = [item["title"] for item in SHOWCASES if not item["url"]]
    if without_link:
        print(f"Примеры без ссылки на бота: {', '.join(without_link)}")
    print("Структура showcase_bot корректна.")


if __name__ == "__main__":
    main()
