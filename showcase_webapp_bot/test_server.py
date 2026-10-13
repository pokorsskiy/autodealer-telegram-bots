"""Проверки каталога и закрытой веб-админки."""

import hashlib
import hmac
import io
import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlencode

from werkzeug.security import generate_password_hash

import config as config_module

# server.py при импорте создаёт таблицы и учётные записи из .env. Базу
# подменяем до импорта, иначе тесты писали бы в рабочую базу.
# Тесты по умолчанию проверяют рабочую витрину, демо — в DemoModeTest.
_IMPORT_DB_DIR = tempfile.TemporaryDirectory()
config_module.DB_NAME = str(Path(_IMPORT_DB_DIR.name) / "import.db")
config_module.DEMO_MODE = False

import database as database_module
import server as server_module
from webapp import auth as auth_module
from webapp import demo as demo_module
from webapp import notifications as notifications_module
from webapp import public as public_module


class AdminServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        temp_path = Path(self.temp_dir.name)
        self.db_patcher = patch.object(
            config_module, "DB_NAME", str(temp_path / "test.db")
        )
        self.upload_patcher = patch.object(
            config_module, "UPLOAD_DIR", temp_path / "uploads"
        )
        self.db_patcher.start()
        self.upload_patcher.start()
        config_module.UPLOAD_DIR.mkdir()
        database_module.init_db()
        database_module.create_initial_owner(
            "owner", generate_password_hash("very-long-test-password")
        )
        server_module.app.config.update(
            TESTING=True, SECRET_KEY="test-secret", SESSION_COOKIE_SECURE=False
        )
        self.client = server_module.app.test_client()

    def tearDown(self) -> None:
        self.upload_patcher.stop()
        self.db_patcher.stop()
        self.temp_dir.cleanup()

    def login_owner(self) -> None:
        owner = database_module.get_admin_by_username("owner")
        with self.client.session_transaction() as session:
            session["admin_id"] = owner["id"]
            session["csrf_token"] = "csrf-test"

    def test_old_demo_photo_links_become_local(self) -> None:
        """Демо-фото из старых баз переезжают с чужих сайтов в web/demo/."""
        old_url, new_url = next(iter(database_module.DEMO_IMAGE_MOVES.items()))
        with closing(sqlite3.connect(config_module.DB_NAME)) as connection, connection:
            connection.execute("UPDATE car_images SET url = ?", (old_url,))
        database_module.init_db()
        with closing(sqlite3.connect(config_module.DB_NAME)) as connection:
            urls = {row[0] for row in connection.execute("SELECT url FROM car_images")}
        self.assertEqual(urls, {new_url})
        self.assertTrue((public_module.WEB_DIR / new_url.lstrip("/")).exists())

    def test_public_catalog_does_not_return_hidden_car(self) -> None:
        car = database_module.get_car("toyota-camry-2024")
        car["is_visible"] = False
        database_module.save_car(car, original_id=car["id"])
        response = self.client.get("/api/cars")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.get_json()["cars"]}
        self.assertNotIn("toyota-camry-2024", ids)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_admin_api_requires_login_and_csrf(self) -> None:
        self.assertEqual(self.client.get("/api/admin/cars").status_code, 401)
        self.login_owner()
        response = self.client.post("/api/admin/cars", json={})
        self.assertEqual(response.status_code, 403)

    def test_owner_can_login_and_login_assets_are_public(self) -> None:
        page = self.client.get("/admin/login")
        self.assertEqual(page.status_code, 200)
        asset_response = self.client.get("/admin/admin.css")
        self.assertEqual(asset_response.status_code, 200)
        asset_response.close()
        with self.client.session_transaction() as session:
            csrf_token = session["csrf_token"]
        response = self.client.post(
            "/admin/login",
            data={
                "csrf_token": csrf_token,
                "username": "owner",
                "password": "very-long-test-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/admin"))

    def test_login_explains_when_owner_is_not_created(self) -> None:
        with closing(sqlite3.connect(config_module.DB_NAME)) as connection:
            with connection:
                connection.execute("DELETE FROM admin_users")
        with (
            patch.object(config_module, "ADMIN_USERNAME", "owner"),
            patch.object(config_module, "ADMIN_PASSWORD", "short"),
        ):
            response = self.client.get("/admin/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "ADMIN_PASSWORD должен содержать".encode(),
            response.data,
        )

    def test_owner_can_create_update_and_delete_car(self) -> None:
        self.login_owner()
        payload = {
            "id": "test-car-2026",
            "brand": "Test",
            "model": "Car",
            "year": 2026,
            "price": 5_000_000,
            "mileage": 0,
            "body": "Седан",
            "drive": "Полный",
            "engine": "2.0 л",
            "power": "200 л.с.",
            "description": "Тестовый автомобиль",
            "location": "port",
            "is_visible": True,
            "sort_order": 0,
        }
        headers = {"X-CSRF-Token": "csrf-test"}
        created = self.client.post(
            "/api/admin/cars", json=payload, headers=headers
        )
        self.assertEqual(created.status_code, 201)

        payload["price"] = 5_500_000
        payload["is_visible"] = False
        updated = self.client.put(
            "/api/admin/cars/test-car-2026", json=payload, headers=headers
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["car"]["price"], 5_500_000)
        self.assertFalse(updated.get_json()["car"]["is_visible"])

        deleted = self.client.delete(
            "/api/admin/cars/test-car-2026", headers=headers
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertIsNone(database_module.get_car("test-car-2026"))

    def test_manager_cannot_delete_car(self) -> None:
        manager_id = database_module.create_admin(
            "manager", generate_password_hash("very-long-test-password"), "manager"
        )
        with self.client.session_transaction() as session:
            session["admin_id"] = manager_id
            session["csrf_token"] = "csrf-test"
        response = self.client.delete(
            "/api/admin/cars/toyota-camry-2024",
            headers={"X-CSRF-Token": "csrf-test"},
        )
        self.assertEqual(response.status_code, 403)

    def test_owner_can_upload_and_delete_image(self) -> None:
        self.login_owner()
        response = self.client.post(
            "/api/admin/cars/toyota-camry-2024/images",
            data={"image": (io.BytesIO(b"RIFF\x00\x00\x00\x00WEBPdata"), "car.webp")},
            headers={"X-CSRF-Token": "csrf-test"},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        uploaded = config_module.UPLOAD_DIR / Path(body["url"]).name
        self.assertTrue(uploaded.exists())

        deleted = self.client.delete(
            f"/api/admin/images/{body['image_id']}",
            headers={"X-CSRF-Token": "csrf-test"},
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(uploaded.exists())


class LegalPagesTest(unittest.TestCase):
    """Политика и согласие: образец в демо, реквизиты заказчика в рабочей витрине."""

    LEGAL = {
        "operator": "ООО «Тест-Авто»", "inn": "4200000000", "ogrn": "1024200000000",
        "address": "г. Кемерово", "email": "pd@test.ru", "contact": "@test_manager",
        "responsible": "директор", "bot": "@test_auto_bot", "processor": "Иванов И. И.",
        "processor_inn": "420000000000", "storage": "3 лет", "updated": "07.10.2026",
    }

    def setUp(self) -> None:
        self.client = server_module.app.test_client()

    def test_demo_shows_sample(self) -> None:
        with patch.object(config_module, "DEMO_MODE", True):
            for path in ("/privacy", "/consent"):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("Образец для демо", response.get_data(as_text=True))

    def test_working_site_shows_customer_details(self) -> None:
        with (
            patch.object(config_module, "DEMO_MODE", False),
            patch.object(config_module, "LEGAL", self.LEGAL),
            patch.object(config_module, "LEGAL_MISSING", []),
        ):
            for path in ("/privacy", "/consent"):
                page = self.client.get(path).get_data(as_text=True)
                self.assertIn("ООО «Тест-Авто»", page)
                self.assertIn("@test_auto_bot", page)
                self.assertNotIn("Образец для демо", page)

    def test_working_site_without_details_hides_pages(self) -> None:
        with (
            patch.object(config_module, "DEMO_MODE", False),
            patch.object(config_module, "LEGAL_MISSING", ["operator"]),
        ):
            self.assertEqual(self.client.get("/privacy").status_code, 404)
            self.assertEqual(self.client.get("/consent").status_code, 404)

    def test_form_has_consent_checkbox(self) -> None:
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('name="consent"', page)
        self.assertIn('href="/consent"', page)
        self.assertIn('href="/privacy"', page)


if __name__ == "__main__":
    unittest.main()


class PublicLeadTest(unittest.TestCase):
    """Заявка из браузера сохраняется и уходит владельцу в Telegram."""

    def setUp(self) -> None:
        self.client = server_module.app.test_client()
        public_module.lead_attempts.clear()

    def _payload(self, **overrides):
        payload = {
            "name": "Иван",
            "phone": "+7 999 000-00-00",
            "username": "@ivan",
            "car_interest": "Toyota Camry",
            "purchase_method": "Наличные",
            "comment": "",
            "lead_type": "car", "consent": "1",
            "car_id": "toyota-camry-2024",
        }
        payload.update(overrides)
        return payload

    def test_valid_lead_is_saved_and_sent(self) -> None:
        with (
            patch.object(public_module, "save_lead", return_value=77) as save,
            patch.object(public_module, "notify_lead", return_value=True) as notify,
        ):
            response = self.client.post("/api/leads", json=self._payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["lead_id"], 77)
        self.assertEqual(save.call_args.kwargs["source"], "site")
        notify.assert_called_once()

    def test_short_phone_is_rejected(self) -> None:
        with patch.object(public_module, "save_lead") as save:
            response = self.client.post("/api/leads", json=self._payload(phone="123"))
        self.assertEqual(response.status_code, 400)
        save.assert_not_called()

    def test_lead_without_consent_is_rejected(self) -> None:
        """Без согласия на обработку персональных данных заявку не сохраняем."""
        for consent in ("", "0", None):
            with patch.object(public_module, "save_lead") as save:
                response = self.client.post("/api/leads", json=self._payload(consent=consent))
            self.assertEqual(response.status_code, 400)
            self.assertIn("согласие", response.get_json()["error"])
            save.assert_not_called()

    def test_flood_is_limited(self) -> None:
        with (
            patch.object(public_module, "save_lead", return_value=1),
            patch.object(public_module, "notify_lead", return_value=True),
        ):
            for _ in range(public_module.LEAD_MAX_PER_WINDOW):
                self.client.post("/api/leads", json=self._payload())
            response = self.client.post("/api/leads", json=self._payload())
        self.assertEqual(response.status_code, 429)

    def test_undelivered_lead_is_still_accepted(self) -> None:
        """Telegram может быть недоступен: заявку всё равно не теряем."""
        with (
            patch.object(public_module, "save_lead", return_value=5),
            patch.object(public_module, "notify_lead", return_value=False),
        ):
            response = self.client.post("/api/leads", json=self._payload())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["delivered"])

    def test_lead_is_sent_to_main_and_extra_bots(self) -> None:
        """Заявка с сайта приходит и в основной бот, и в гибрид."""
        with (
            patch.object(config_module, "TOKEN", "111:main-token"),
            patch.object(config_module, "ADMIN_EXTRA_BOT_TOKENS", ["222:hybrid-token"]),
            patch.object(config_module, "YOUR_CHAT_ID", 555),
            patch.object(notifications_module.requests, "post") as post,
        ):
            post.return_value.status_code = 200
            delivered = notifications_module.notify_lead(7, self._payload())
        self.assertTrue(delivered)
        main_call, hybrid_call = post.call_args_list
        self.assertIn("bot111:main-token/", main_call.args[0])
        self.assertIn("bot222:hybrid-token/", hybrid_call.args[0])
        self.assertEqual(hybrid_call.kwargs["json"]["chat_id"], 555)
        # Кнопку «Взял в работу» умеет обрабатывать только основной бот.
        self.assertIn("reply_markup", main_call.kwargs["json"])
        self.assertNotIn("reply_markup", hybrid_call.kwargs["json"])

    def test_notice_without_contacts_keeps_personal_data_out_of_telegram(self) -> None:
        """LEAD_NOTIFY_CONTACTS=0: в Telegram ни имени, ни телефона, есть кнопка админки."""
        with (
            patch.object(config_module, "TOKEN", "111:main-token"),
            patch.object(config_module, "ADMIN_EXTRA_BOT_TOKENS", ["222:hybrid-token"]),
            patch.object(config_module, "YOUR_CHAT_ID", 555),
            patch.object(config_module, "LEAD_NOTIFY_CONTACTS", False),
            patch.object(config_module, "ADMIN_WEB_APP_URL", "https://acme.example.com/admin/tg"),
            patch.object(notifications_module.requests, "post") as post,
        ):
            post.return_value.status_code = 200
            delivered = notifications_module.notify_lead(
                7, self._payload(comment="Позвоните Ивану"),
                {"id": 101, "first_name": "Иван", "username": "ivan"},
            )
        self.assertTrue(delivered)
        main_call, hybrid_call = post.call_args_list
        for call in (main_call, hybrid_call):
            text = call.kwargs["json"]["text"]
            self.assertIn("№7", text)
            self.assertIn("Toyota Camry", text)
            for secret in ("Иван", "000-00-00", "@ivan", "101"):
                self.assertNotIn(secret, text)
        main_rows = main_call.kwargs["json"]["reply_markup"]["inline_keyboard"]
        self.assertEqual(main_rows[0][0]["callback_data"], "lead:take:7")
        self.assertEqual(main_rows[1][0]["web_app"]["url"], "https://acme.example.com/admin/tg")
        # Гибриду — только кнопка админки: «Взял в работу» обрабатывает основной бот.
        hybrid_rows = hybrid_call.kwargs["json"]["reply_markup"]["inline_keyboard"]
        self.assertEqual(len(hybrid_rows), 1)
        self.assertIn("web_app", hybrid_rows[0][0])

    def test_notice_to_group_opens_admin_by_link(self) -> None:
        """В группе Web App-кнопки запрещены: админка открывается обычной ссылкой."""
        with (
            patch.object(config_module, "YOUR_CHAT_ID", -100500),
            patch.object(config_module, "ADMIN_WEB_APP_URL", "https://acme.example.com/admin/tg"),
        ):
            button = notifications_module.admin_button()
        self.assertEqual(button["url"], "https://acme.example.com/admin")

    def test_admin_leads_require_login(self) -> None:
        self.assertEqual(self.client.get("/api/admin/leads").status_code, 401)


class DemoModeTest(unittest.TestCase):
    """В демо сервер заявок не принимает ни с сайта, ни из гибрида."""

    def setUp(self) -> None:
        self.client = server_module.app.test_client()
        public_module.lead_attempts.clear()
        demo_patch = patch.object(config_module, "DEMO_MODE", True)
        demo_patch.start()
        self.addCleanup(demo_patch.stop)

    def test_site_reports_demo_and_owner(self) -> None:
        with (
            patch.object(config_module, "SITE_OWNER", "Иванов Иван"),
            patch.object(config_module, "SITE_EMAIL", "owner@example.com"),
        ):
            data = self.client.get("/api/site").get_json()
        self.assertEqual(
            data, {"demo": True, "owner": "Иванов Иван", "email": "owner@example.com"}
        )

    def test_prospect_demo_is_served_only_in_demo_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            demo_dir = Path(temp_dir) / "avtoyug"
            demo_dir.mkdir()
            (demo_dir / "demo.json").write_text(
                json.dumps({"brand": "АвтоЮг", "color": "#1e6fd9", "cars": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            (demo_dir / "car.jpg").write_bytes(b"\xff\xd8\xff")
            with patch.object(demo_module, "DEMOS_DIR", Path(temp_dir)):
                demo = self.client.get("/api/demos/avtoyug")
                image = self.client.get("/demos/avtoyug/car.jpg")
                missing = self.client.get("/api/demos/nobody")
                bad_slug = self.client.get("/api/demos/Avto_Yug")
                with patch.object(config_module, "DEMO_MODE", False):
                    working_site = self.client.get("/api/demos/avtoyug")
            image.close()
        self.assertEqual(demo.get_json()["brand"], "АвтоЮг")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(bad_slug.status_code, 404)
        self.assertEqual(working_site.status_code, 404)

    def _sandbox_demo(self, temp_dir: str, **extra: Any) -> ExitStack:
        demo_dir = Path(temp_dir) / "demos" / "acme"
        demo_dir.mkdir(parents=True)
        base_car = {"id": "audi-q3", "brand": "Audi", "model": "Q3", "location": "city",
                    "images": [{"url": "/demos/acme/audi-1.jpg"}]}
        (demo_dir / "demo.json").write_text(
            json.dumps({"brand": "Велма", "cars": [base_car], **extra}, ensure_ascii=False),
            encoding="utf-8",
        )
        stack = ExitStack()
        stack.enter_context(patch.object(demo_module, "DEMOS_DIR", Path(temp_dir) / "demos"))
        stack.enter_context(
            patch.object(demo_module, "DEMO_SANDBOX_DIR", Path(temp_dir) / "boxes")
        )
        demo_module.demo_sandbox_writes.clear()
        return stack

    def test_sandbox_changes_are_seen_only_by_their_owner(self) -> None:
        new_car = {"id": "kia-k5", "brand": "Kia", "model": "K5", "location": "port", "price": 2000000,
                   "images": [{"url": "https://evil.example/x.jpg"}, {"url": "/demos/acme/audi-1.jpg"}]}
        with tempfile.TemporaryDirectory() as temp_dir, self._sandbox_demo(temp_dir):
            saved = self.client.put("/api/demos/acme/sandbox", json={"cars": [new_car]})
            mine = self.client.get("/api/demos/acme").get_json()
            stranger = server_module.app.test_client().get("/api/demos/acme").get_json()
            self.client.delete("/api/demos/acme/sandbox")
            after_reset = self.client.get("/api/demos/acme").get_json()
        self.assertEqual(saved.status_code, 200)
        self.assertIn("demo_sb=", saved.headers.get("Set-Cookie", ""))
        self.assertTrue(mine["sandbox"])
        self.assertEqual([car["id"] for car in mine["cars"]], ["kia-k5"])
        # Чужие ссылки на фото отбрасываются, фото самого демо остаются.
        self.assertEqual(mine["cars"][0]["images"], [
            {"url": "/demos/acme/audi-1.jpg", "alt_text": "", "sort_order": 0}
        ])
        self.assertEqual([car["id"] for car in stranger["cars"]], ["audi-q3"])
        self.assertNotIn("sandbox", stranger)
        self.assertEqual([car["id"] for car in after_reset["cars"]], ["audi-q3"])

    def test_sandbox_photos_are_checked_and_served_to_the_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, self._sandbox_demo(temp_dir):
            fake = self.client.post(
                "/api/demos/acme/sandbox/photos",
                data={"image": (io.BytesIO(b"not an image"), "car.jpg")},
                content_type="multipart/form-data",
            )
            good = self.client.post(
                "/api/demos/acme/sandbox/photos",
                data={"image": (io.BytesIO(b"\xff\xd8\xff\xe0" + b"0" * 64), "car.jpg")},
                content_type="multipart/form-data",
            )
            url = good.get_json()["urls"][0]
            image = self.client.get(url)
            image.close()
        self.assertEqual(fake.status_code, 400)
        self.assertEqual(good.status_code, 201)
        self.assertRegex(url, r"^/demo-sandbox/acme/[0-9a-f]{32}/[0-9a-f]{16}\.jpg$")
        self.assertEqual(image.status_code, 200)

    def test_sandbox_follows_telegram_account_across_mini_apps(self) -> None:
        # Каталог и админка — два мини-приложения без общей cookie: хозяина узнаём по аккаунту.
        car = {"id": "kia-k5", "brand": "Kia", "model": "K5", "location": "port"}
        with (
            tempfile.TemporaryDirectory() as temp_dir, self._sandbox_demo(temp_dir),
            patch.object(config_module, "TOKEN", "123:demo-token"),
        ):
            admin = server_module.app.test_client()
            catalog = server_module.app.test_client()
            mine = {"X-Telegram-Init-Data": signed_init_data("123:demo-token", 555)}
            other = {"X-Telegram-Init-Data": signed_init_data("123:demo-token", 777)}
            forged = {"X-Telegram-Init-Data": signed_init_data("999:wrong-token", 555)}
            admin.put("/api/demos/acme/sandbox", json={"cars": [car]}, headers=mine)
            seen = catalog.get("/api/demos/acme", headers=mine).get_json()
            not_seen = catalog.get("/api/demos/acme", headers=other).get_json()
            forged_seen = catalog.get("/api/demos/acme", headers=forged).get_json()
        self.assertEqual([c["id"] for c in seen["cars"]], ["kia-k5"])
        self.assertEqual([c["id"] for c in not_seen["cars"]], ["audi-q3"])
        self.assertEqual([c["id"] for c in forged_seen["cars"]], ["audi-q3"])

    def test_expired_demo_closes_catalog_and_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, self._sandbox_demo(temp_dir, expires="2020-01-01"):
            demo = self.client.get("/api/demos/acme")
            write = self.client.put("/api/demos/acme/sandbox", json={"cars": []})
        self.assertEqual(demo.status_code, 410)
        self.assertEqual(demo.get_json(), {"expired": True, "brand": "Велма"})
        self.assertEqual(write.status_code, 410)

    def test_sandbox_is_closed_outside_demo_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, self._sandbox_demo(temp_dir):
            with patch.object(config_module, "DEMO_MODE", False):
                write = self.client.put("/api/demos/acme/sandbox", json={"cars": []})
        self.assertEqual(write.status_code, 404)

    def test_demo_admin_opens_without_login_and_changes_nothing(self) -> None:
        page = self.client.get("/admin/demo")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('data-demo="1"', html)
        self.assertNotIn("/admin/logout", html)
        # Страница не открывает сессию: настоящая админка по-прежнему закрыта.
        self.assertEqual(self.client.get("/api/admin/cars").status_code, 401)
        self.assertEqual(self.client.get("/admin").status_code, 302)
        with patch.object(config_module, "DEMO_MODE", False):
            self.assertEqual(self.client.get("/admin/demo").status_code, 404)

    def test_leads_are_refused_without_saving(self) -> None:
        payload = {
            "name": "Иван", "phone": "+7 999 000-00-00", "username": "",
            "car_interest": "Toyota Camry", "purchase_method": "Наличные",
            "comment": "", "lead_type": "car", "consent": "1", "car_id": "toyota-camry-2024",
        }
        with (
            patch.object(public_module, "save_lead") as save,
            patch.object(public_module, "notify_lead") as notify,
        ):
            site = self.client.post("/api/leads", json=payload)
            bot = self.client.post("/api/bot/leads", json={"lead": payload})
        self.assertEqual(site.status_code, 403)
        self.assertEqual(bot.status_code, 403)
        save.assert_not_called()
        notify.assert_not_called()


class TelegramLeadTest(unittest.TestCase):
    """Внутри Telegram витрина шлёт заявку на сервер с подписанными данными запуска."""

    def setUp(self) -> None:
        self.client = server_module.app.test_client()
        public_module.lead_attempts.clear()
        token_patch = patch.object(config_module, "TOKEN", "111:main-token")
        token_patch.start()
        self.addCleanup(token_patch.stop)

    def post(self, init_data: str):
        payload = {
            "name": "Иван", "phone": "+7 999 000-00-00", "username": "",
            "car_interest": "Toyota Camry", "purchase_method": "Наличные",
            "comment": "", "lead_type": "car", "consent": "1", "car_id": "toyota-camry-2024",
            "init_data": init_data,
        }
        with (
            patch.object(public_module, "save_lead", return_value=78) as save,
            patch.object(public_module, "notify_lead", return_value=True) as notify,
        ):
            response = self.client.post("/api/leads", json=payload)
        return response, save, notify

    def test_signed_lead_keeps_telegram_profile(self) -> None:
        response, save, notify = self.post(signed_init_data("111:main-token", 555))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(save.call_args.args[0], 555)
        self.assertNotIn("source", save.call_args.kwargs)
        self.assertEqual(notify.call_args.args[2]["id"], 555)

    def test_forged_init_data_counts_as_site_lead(self) -> None:
        response, save, notify = self.post(signed_init_data("333:other-token", 555))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(save.call_args.args[0], 0)
        self.assertEqual(save.call_args.kwargs["source"], "site")
        self.assertIsNone(notify.call_args.args[2])


class LeadWorkflowTest(unittest.TestCase):
    """Статусы, выгрузка и роли: работа менеджера внутри админки."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        temp_path = Path(self.temp_dir.name)
        self.db_patch = patch.object(config_module, "DB_NAME", str(temp_path / "test.db"))
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)
        database_module.init_db()
        self.client = server_module.app.test_client()

    def _login_as(self, role: str) -> None:
        admin_id = database_module.create_admin(
            f"user-{role}", generate_password_hash("password-12345"), role
        )
        with self.client.session_transaction() as session:
            session["admin_id"] = admin_id
            session["csrf_token"] = "token"

    def _lead(self) -> int:
        return database_module.save_lead(
            0,
            None,
            {
                "name": "Иван", "phone": "+79990000000", "car_interest": "Camry",
                "purchase_method": "Наличные", "comment": "", "lead_type": "car", "consent": "1",
                "username": "", "car_id": "",
            },
            source="site",
        )

    def test_consent_time_is_saved_with_lead(self) -> None:
        lead = database_module.get_lead(self._lead())
        self.assertTrue(lead["consent_at"])
        self.assertEqual(lead["consent_at"], lead["created_at"])

    def test_status_and_note_are_saved(self) -> None:
        lead_id = self._lead()
        self._login_as("manager")
        response = self.client.patch(
            f"/api/admin/leads/{lead_id}",
            json={"status": "in_work", "note": "Перезвонить в среду"},
            headers={"X-CSRF-Token": "token"},
        )
        self.assertEqual(response.status_code, 204)
        lead = database_module.get_lead(lead_id)
        self.assertEqual(lead["status"], "in_work")
        self.assertEqual(lead["note"], "Перезвонить в среду")
        self.assertEqual(lead["handled_by"], "user-manager")

    def test_unknown_status_is_rejected(self) -> None:
        lead_id = self._lead()
        self._login_as("manager")
        response = self.client.patch(
            f"/api/admin/leads/{lead_id}",
            json={"status": "готово"},
            headers={"X-CSRF-Token": "token"},
        )
        self.assertEqual(response.status_code, 400)

    def test_csv_export_has_bom_for_excel(self) -> None:
        self._lead()
        self._login_as("owner")
        response = self.client.get("/api/admin/leads.csv")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_data(as_text=True).startswith("\ufeff"))

    def _post_user(self, username: str, role: str):
        return self.client.post(
            "/api/admin/users",
            json={"username": username, "password": "password-12345", "role": role},
            headers={"X-CSRF-Token": "token"},
        )

    def test_owner_manages_only_managers(self) -> None:
        """Владелец заводит своих менеджеров, но не владельцев и не разработчика."""
        developer_id = database_module.create_admin(
            "dev", generate_password_hash("password-12345"), "developer"
        )
        self._login_as("owner")
        self.assertEqual(self._post_user("owner2", "owner").status_code, 403)
        created = self._post_user("manager1", "manager")
        self.assertEqual(created.status_code, 201)
        manager_id = created.get_json()["id"]

        promoted = self.client.put(
            f"/api/admin/users/{manager_id}",
            json={"role": "owner", "is_active": True},
            headers={"X-CSRF-Token": "token"},
        )
        self.assertEqual(promoted.status_code, 403)
        disabled = self.client.put(
            f"/api/admin/users/{manager_id}",
            json={"role": "manager", "is_active": False},
            headers={"X-CSRF-Token": "token"},
        )
        self.assertEqual(disabled.status_code, 204)
        untouchable = self.client.delete(
            f"/api/admin/users/{developer_id}", headers={"X-CSRF-Token": "token"}
        )
        self.assertEqual(untouchable.status_code, 403)

        users = {
            user["username"]: user
            for user in self.client.get("/api/admin/users").get_json()["users"]
        }
        self.assertTrue(users["manager1"]["can_manage"])
        self.assertFalse(users["dev"]["can_manage"])
        self.assertEqual(
            self.client.get("/api/admin/users").get_json()["assignable_roles"], ["manager"]
        )

        deleted = self.client.delete(
            f"/api/admin/users/{manager_id}", headers={"X-CSRF-Token": "token"}
        )
        self.assertEqual(deleted.status_code, 204)

    def test_manager_cannot_manage_accounts(self) -> None:
        self._login_as("manager")
        self.assertEqual(self._post_user("manager1", "manager").status_code, 403)

    def test_developer_manages_all_roles(self) -> None:
        self._login_as("developer")
        created = self._post_user("owner2", "owner")
        self.assertEqual(created.status_code, 201)
        deleted = self.client.delete(
            f"/api/admin/users/{created.get_json()['id']}",
            headers={"X-CSRF-Token": "token"},
        )
        self.assertEqual(deleted.status_code, 204)

    def test_initial_developer_is_created_once(self) -> None:
        self.assertTrue(
            database_module.create_initial_developer("dev", generate_password_hash("x" * 12))
        )
        self.assertFalse(
            database_module.create_initial_developer("dev2", generate_password_hash("x" * 12))
        )
        self.assertEqual(database_module.get_admin_by_username("dev")["role"], "developer")
        self.assertIsNone(database_module.get_admin_by_username("dev2"))

    def test_manager_archives_lead_but_cannot_delete(self) -> None:
        lead_id = self._lead()
        self._login_as("manager")
        headers = {"X-CSRF-Token": "token"}
        self.assertEqual(
            database_module.catalog_summary()["leads_new"], 1
        )
        response = self.client.post(
            f"/api/admin/leads/{lead_id}/archive", json={"archived": True}, headers=headers
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(database_module.get_lead(lead_id)["is_archived"], 1)
        # Новая заявка в архиве не считается «без ответа».
        self.assertEqual(self.client.get("/api/admin/summary").get_json()["leads_new"], 0)
        self.assertIn("да", self.client.get("/api/admin/leads.csv").get_data(as_text=True))

        response = self.client.delete(f"/api/admin/leads/{lead_id}", headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertIsNotNone(database_module.get_lead(lead_id))

        self.client.post(
            f"/api/admin/leads/{lead_id}/archive", json={"archived": False}, headers=headers
        )
        self.assertEqual(database_module.get_lead(lead_id)["is_archived"], 0)

    def test_owner_deletes_lead(self) -> None:
        lead_id = self._lead()
        self._login_as("owner")
        headers = {"X-CSRF-Token": "token"}
        self.assertEqual(self.client.delete(f"/api/admin/leads/{lead_id}").status_code, 403)
        response = self.client.delete(f"/api/admin/leads/{lead_id}", headers=headers)
        self.assertEqual(response.status_code, 204)
        self.assertIsNone(database_module.get_lead(lead_id))
        self.assertEqual(
            self.client.delete(f"/api/admin/leads/{lead_id}", headers=headers).status_code, 404
        )
        self.assertEqual(database_module.list_actions()[0]["action"], "Удалил заявку")

    def test_sold_car_leaves_catalog_but_stays_in_admin(self) -> None:
        self._login_as("manager")
        car_id = database_module.list_cars(include_hidden=True)[0]["id"]
        response = self.client.post(
            f"/api/admin/cars/{car_id}/sold",
            json={"sold": True},
            headers={"X-CSRF-Token": "token"},
        )
        self.assertEqual(response.status_code, 204)
        self.assertNotIn(car_id, [car["id"] for car in database_module.list_cars()])
        self.assertIn(car_id, [car["id"] for car in database_module.list_cars(include_hidden=True)])

    def test_actions_are_logged(self) -> None:
        lead_id = self._lead()
        self._login_as("manager")
        self.client.patch(
            f"/api/admin/leads/{lead_id}",
            json={"status": "won"},
            headers={"X-CSRF-Token": "token"},
        )
        actions = database_module.list_actions()
        self.assertEqual(actions[0]["username"], "user-manager")
        self.assertIn("заявку", actions[0]["action"])


def signed_init_data(token: str, telegram_id: int, auth_date: int | None = None) -> str:
    """Данные Web App так, как их подписывает Telegram."""
    fields = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAH-test",
        "user": json.dumps({"id": telegram_id, "first_name": "Тест"}),
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class TelegramLoginTest(unittest.TestCase):
    """Вход в админку кнопкой /admin из бота, без пароля."""

    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_patch = patch.object(config_module, "DB_NAME", str(Path(temp_dir.name) / "test.db"))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database_module.init_db()
        database_module.create_initial_owner("owner", generate_password_hash("very-long-test-password"))
        server_module.app.config.update(
            TESTING=True, SECRET_KEY="test-secret", SESSION_COOKIE_SECURE=False
        )
        self.client = server_module.app.test_client()
        auth_module.login_attempts.clear()
        for name, value in {
            "TOKEN": "111:main-token",
            "ADMIN_EXTRA_BOT_TOKENS": ["222:hybrid-token"],
            "TELEGRAM_ADMINS": {555: "owner"},
        }.items():
            patcher = patch.object(config_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with self.client.session_transaction() as session:
            session["csrf_token"] = "csrf-test"

    def telegram_login(self, init_data: str):
        return self.client.post(
            "/admin/tg",
            json={"init_data": init_data},
            headers={"X-CSRF-Token": "csrf-test"},
        )

    def test_listed_account_enters_without_password(self) -> None:
        self.assertEqual(self.client.get("/admin/tg").status_code, 200)
        response = self.telegram_login(signed_init_data("111:main-token", 555))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["redirect"], "/admin")
        self.assertEqual(self.client.get("/api/admin/session").status_code, 200)

    def test_hybrid_bot_signature_is_accepted(self) -> None:
        response = self.telegram_login(signed_init_data("222:hybrid-token", 555))
        self.assertEqual(response.status_code, 200)

    def test_rejected_logins(self) -> None:
        cases = {
            "чужой бот": signed_init_data("333:other-token", 555),
            "нет в списке": signed_init_data("111:main-token", 777),
            "устарели": signed_init_data("111:main-token", 555, int(time.time()) - 7200),
            "подделан ID": signed_init_data("111:main-token", 555).replace("555", "556"),
            "не данные Telegram": "hello",
        }
        for name, init_data in cases.items():
            with self.subTest(name):
                auth_module.login_attempts.clear()
                self.assertEqual(self.telegram_login(init_data).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/session").status_code, 401)

    def test_disabled_account_cannot_enter(self) -> None:
        owner = database_module.get_admin_by_username("owner")
        database_module.update_admin(
            owner["id"], password_hash=None, role="owner", is_active=False
        )
        response = self.telegram_login(signed_init_data("111:main-token", 555))
        self.assertEqual(response.status_code, 403)

    def test_login_requires_csrf(self) -> None:
        response = self.client.post(
            "/admin/tg", json={"init_data": signed_init_data("111:main-token", 555)}
        )
        self.assertEqual(response.status_code, 403)


class BotLeadTest(unittest.TestCase):
    """Гибрид передаёт свои заявки в админку подписанным запросом."""

    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_patch = patch.object(config_module, "DB_NAME", str(Path(temp_dir.name) / "test.db"))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database_module.init_db()
        tokens_patch = patch.object(config_module, "ADMIN_EXTRA_BOT_TOKENS", ["222:hybrid-token"])
        tokens_patch.start()
        self.addCleanup(tokens_patch.stop)
        self.client = server_module.app.test_client()

    def send(self, token: str = "222:hybrid-token", **overrides):
        payload = {
            "lead": {
                "lead_type": "car", "consent": "1", "name": "Иван", "phone": "+7 999 123-45-67",
                "username": "@ivan", "car_interest": "BMW X5 (2023)",
                "purchase_method": "Наличные", "comment": "", "car_id": "bmw-x5-2023",
            },
            "user_id": 101,
            "username": "ivan_auto",
            "sent_at": int(time.time()),
        }
        payload.update(overrides)
        body = json.dumps(payload).encode()
        signature = hmac.new(token.encode(), body, hashlib.sha256).hexdigest()
        return self.client.post(
            "/api/bot/leads",
            data=body,
            headers={"Content-Type": "application/json", "X-Bot-Signature": signature},
        )

    def test_signed_lead_is_saved_without_second_notification(self) -> None:
        with patch.object(public_module, "notify_lead") as notify:
            response = self.send()
        self.assertEqual(response.status_code, 200)
        lead = database_module.get_lead(response.get_json()["lead_id"])
        self.assertEqual(lead["source"], "telegram")
        self.assertEqual(lead["username"], "ivan_auto")
        self.assertEqual(lead["car_interest"], "BMW X5 (2023)")
        notify.assert_not_called()

    def test_rejected_bot_leads(self) -> None:
        self.assertEqual(self.send(token="333:other-token").status_code, 403)
        self.assertEqual(self.send(sent_at=int(time.time()) - 3600).status_code, 403)
        self.assertEqual(self.send(lead={"name": "И"}).status_code, 400)
        self.assertEqual(database_module.list_leads(), [])
