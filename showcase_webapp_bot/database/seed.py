"""Демонстрационный каталог: с ним новая база не открывается пустой."""

import sqlite3

from database.connection import utc_now

DEMO_CARS = (
    {
        "id": "toyota-camry-2024",
        "brand": "Toyota",
        "model": "Camry",
        "year": 2024,
        "price": 3_850_000,
        "mileage": 8_000,
        "body": "Седан",
        "drive": "Передний",
        "engine": "2.5 л · бензин",
        "power": "203 л.с.",
        "description": "Комфортный седан для города и трассы с просторным салоном и современными ассистентами.",
        "location": "city",
        "images": (
            "/demo/toyota-camry.png",
        ),
    },
    {
        "id": "bmw-x5-2023",
        "brand": "BMW",
        "model": "X5",
        "year": 2023,
        "price": 8_900_000,
        "mileage": 24_000,
        "body": "Кроссовер",
        "drive": "Полный",
        "engine": "3.0 л · дизель",
        "power": "298 л.с.",
        "description": "Премиальный кроссовер с полным приводом и высоким уровнем комфорта для дальних поездок.",
        "location": "port",
        "images": (
            "/demo/bmw-x5.jpg",
        ),
    },
    {
        "id": "geely-monjaro-2025",
        "brand": "Geely",
        "model": "Monjaro",
        "year": 2025,
        "price": 4_650_000,
        "mileage": 2_000,
        "body": "Кроссовер",
        "drive": "Полный",
        "engine": "2.0 л · бензин",
        "power": "238 л.с.",
        "description": "Современный семейный кроссовер с просторным салоном и богатым набором электронных помощников.",
        "location": "port",
        "images": (
            "/demo/geely-monjaro.png",
        ),
    },
    {
        "id": "audi-q5-2023",
        "brand": "Audi",
        "model": "Q5",
        "year": 2023,
        "price": 7_450_000,
        "mileage": 31_000,
        "body": "Кроссовер",
        "drive": "Полный",
        "engine": "2.0 л · бензин",
        "power": "265 л.с.",
        "description": (
            "Сбалансированный премиальный кроссовер с quattro и удобным размером "
            "для ежедневной эксплуатации."
        ),
        "location": "city",
        "images": (
            "/demo/audi-q5.webp",
        ),
    },
    {
        "id": "kia-sorento-2024",
        "brand": "Kia",
        "model": "Sorento",
        "year": 2024,
        "price": 5_300_000,
        "mileage": 12_000,
        "body": "Внедорожник",
        "drive": "Полный",
        "engine": "2.5 л · бензин",
        "power": "281 л.с.",
        "description": "Практичный семиместный автомобиль для семьи, путешествий и повседневных задач.",
        "location": "city",
        "images": ("/demo/kia-sorento.jpg",),
    },
    {
        "id": "toyota-camry-2022",
        "brand": "Toyota",
        "model": "Camry Prestige",
        "year": 2022,
        "price": 3_300_000,
        "mileage": 54_000,
        "body": "Седан",
        "drive": "Передний",
        "engine": "2.5 л · бензин",
        "power": "200 л.с.",
        "description": "Проверенный седан в богатой комплектации с комфортной подвеской и привычной эргономикой.",
        "location": "city",
        "images": (
            "/demo/toyota-camry.png",
        ),
    },
)


# Раньше демо-фото ссылались на чужие сайты и пропадали вместе с ними.
# Теперь они лежат в web/demo/, а старые адреса в готовых базах заменяются.
DEMO_IMAGE_MOVES = {
    "https://di-uploads-pod10.dealerinspire.com/wilsonvilletoyota/uploads/2023/09/2024camry-1.png":
        "/demo/toyota-camry.png",
    "https://cdn.bimmertoday.de/wp-content/uploads/2023/02/2023-BMW-X5-Facelift-G05-LCI-xLine-Blue-Ridge-Mountain-xDrive50e-42.jpg":
        "/demo/bmw-x5.jpg",
    "https://www.geely.com/-/media/project/web-portal/models/new-monjaro/360-colors/green/green-0.png?h=535&hash=34D9485C11C1E9A5058F48381468D19A&iar=0&w=1500":
        "/demo/geely-monjaro.png",
    "https://images3.kingautos.net/spec/2023/01/kZ6Ro5Oeop2RnpGgmco.webp":
        "/demo/audi-q5.webp",
    "https://www.kiamedia.com/image/landing/21417/1/2/21773?v=3":
        "/demo/kia-sorento.jpg",
}


def localize_demo_images(connection: sqlite3.Connection) -> None:
    for old_url, new_url in DEMO_IMAGE_MOVES.items():
        connection.execute(
            "UPDATE car_images SET url = ? WHERE url = ?", (new_url, old_url)
        )


def seed_catalog(connection: sqlite3.Connection) -> None:
    count = connection.execute("SELECT COUNT(*) FROM catalog_cars").fetchone()[0]
    if count:
        return
    now = utc_now()
    for index, car in enumerate(DEMO_CARS):
        connection.execute(
            """
            INSERT INTO catalog_cars (
                id, brand, model, year, price, mileage, body, drive, engine,
                power, description, location, is_visible, sort_order,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                car["id"],
                car["brand"],
                car["model"],
                car["year"],
                car["price"],
                car["mileage"],
                car["body"],
                car["drive"],
                car["engine"],
                car["power"],
                car["description"],
                car["location"],
                index,
                now,
                now,
            ),
        )
        for image_index, image_url in enumerate(car["images"]):
            connection.execute(
                """
                INSERT INTO car_images (car_id, url, alt_text, sort_order)
                VALUES (?, ?, ?, ?)
                """,
                (
                    car["id"],
                    image_url,
                    f"{car['brand']} {car['model']}",
                    image_index,
                ),
            )
