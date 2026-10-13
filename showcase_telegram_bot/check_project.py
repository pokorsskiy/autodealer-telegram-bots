"""Локальная диагностика демонстрационного Telegram-бота."""

import ast
import os
import sys

from calculator import AGE_3_TO_5, AGE_OVER_5, AGE_UNDER_3, calculate_duty_eur
from config import DEMO_MODE, MANAGER_URL, TOKEN

# В консоли Windows с кодировкой cp1251 эмодзи в выводе роняли скрипт
# UnicodeEncodeError: недостающие символы заменяются, кириллица остаётся.
sys.stdout.reconfigure(errors="replace")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIRED_FILES = (
    "bot.py",
    "calculator.py",
    "config.py",
    "keyboards.py",
    "logger.py",
    "texts.py",
    "test_bot.py",
    ".env.example",
    "menu-cover.jpg",
)


def check_syntax() -> bool:
    valid = True
    for file_name in os.listdir(BASE_DIR):
        if not file_name.endswith(".py"):
            continue
        path = os.path.join(BASE_DIR, file_name)
        try:
            with open(path, encoding="utf-8") as source:
                ast.parse(source.read(), filename=path)
        except SyntaxError as error:
            print(f"❌ {file_name}: {error}")
            valid = False
    return valid


def check_files() -> bool:
    missing = [name for name in REQUIRED_FILES if not os.path.isfile(os.path.join(BASE_DIR, name))]
    if missing:
        print(f"❌ Не найдены файлы: {', '.join(missing)}")
        return False
    return True


def check_calculator() -> bool:
    checks = (
        calculate_duty_eur(10_000, AGE_UNDER_3, 1_500) == 5_250,
        calculate_duty_eur(20_000, AGE_3_TO_5, 2_000) == 5_400,
        calculate_duty_eur(20_000, AGE_OVER_5, 1_600) == 5_600,
    )
    return all(checks)


if __name__ == "__main__":
    results = {
        "Файлы": check_files(),
        "Синтаксис": check_syntax(),
        "Калькулятор": check_calculator(),
        "DEMO_MODE": DEMO_MODE is not None,
    }
    for name, valid in results.items():
        print(f"🔍 {name}:", "OK" if valid else "ошибка")
    if DEMO_MODE is None:
        print("❌ DEMO_MODE не задан: 1 — демо без заявок, 0 — рабочий бот")
    else:
        print("🔍 Режим:", "демо, заявки не отправляются" if DEMO_MODE else "рабочий")
    print("🔍 BOT_TOKEN:", "настроен" if TOKEN else "не задан")
    print("🔍 MANAGER_URL:", "настроен" if MANAGER_URL else "не задан, кнопки «Написать менеджеру» не будет")
    if not all(results.values()):
        raise SystemExit(1)
