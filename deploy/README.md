# Развёртывание на сервере

Образец рассчитан на Ubuntu 24.04, пользователя `admin`, каталог `/opt/autobot`
и домен `example.com` — замените их на свои в `nginx/autobot.conf`, юнитах и скриптах.

Схема:

```
интернет ─ nginx (HTTPS) ─ gunicorn 127.0.0.1:8000 ─ Flask: каталог, API, админка
                                                      └ SQLite + uploads/ на диске
Telegram ◄─ long polling ─ 4 бота, каждый — отдельный сервис systemd
```

Боты работают на long polling, а не на webhook: им не нужны домен и входящие
соединения, и перезапуск одного не задевает остальные.

## 0. Проверить Telegram API с сервера

До установки чего-либо. Из части дата-центров `api.telegram.org` недоступен
или отвечает через раз, и тогда боты падают с `ConnectionError`.

```bash
for i in $(seq 20); do curl -s -o /dev/null -m 10 -w "%{http_code}\n" https://api.telegram.org; done
```

Ожидается 20 ответов `302`. Если есть таймауты — выбрать другую локацию либо
поставить посредника на сервере, где Telegram доступен, и указать его адрес
в `TELEGRAM_API_URL` у Web App-бота и гибрида.

## 1. Система

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip nginx sqlite3 certbot python3-certbot-nginx
```

`sqlite3` нужен скрипту резервного копирования. На сервере с 1 ГБ памяти
добавьте swap, иначе `pip install` упирается в память:

```bash
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 2. Код и зависимости

```bash
sudo mkdir -p /opt/autobot && sudo chown admin:admin /opt/autobot
git clone https://github.com/<пользователь>/autodealer-telegram-bots.git /opt/autobot
cd /opt/autobot
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## 3. Настройки

У каждого бота свой `.env` рядом с кодом и свой `BOT_TOKEN`.

```bash
for bot in showcase_bot showcase_telegram_bot showcase_webapp_bot showcase_hybrid_bot; do
    cp "$bot/.env.example" "$bot/.env" && chmod 600 "$bot/.env"
done
```

У Web App-бота и гибрида `WEB_APP_URL=https://example.com`, у Web App-бота ещё
`SECRET_KEY`, учётная запись владельца и `SESSION_COOKIE_SECURE=1`. Что значит
каждая настройка — в README бота.

## 4. Проверка без запуска

```bash
for bot in showcase_bot showcase_telegram_bot showcase_webapp_bot showcase_hybrid_bot; do
    (cd "$bot" && ../venv/bin/python check_project.py && ../venv/bin/python -m unittest --quiet)
done
```

## 5. Сервисы

```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autobot-web autobot-main autobot-telegram autobot-webapp-bot autobot-hybrid
```

## 6. Сертификат и nginx

Сертификат выпускается до подключения конфигурации: иначе `nginx -t` не найдёт
его файлы. A-записи домена уже должны указывать на сервер.

```bash
sudo certbot certonly --nginx -d example.com -d www.example.com
sudo cp deploy/nginx/autobot.conf /etc/nginx/sites-available/autobot
sudo ln -sfn /etc/nginx/sites-available/autobot /etc/nginx/sites-enabled/autobot
sudo nginx -t && sudo systemctl reload nginx
```

## 7. Резервные копии

`backup.sh` раз в сутки снимает согласованные копии всех SQLite-баз через
`sqlite3 .backup` и архивирует `uploads/`; копии старше 14 дней удаляются.

```bash
sudo systemctl enable --now autobot-backup.timer
sudo systemctl start autobot-backup.service
sudo ls -la /var/backups/autobot
```

## 8. Проверка

```bash
sudo systemctl is-active autobot-web autobot-main autobot-telegram autobot-webapp-bot autobot-hybrid
curl -I https://example.com
sudo journalctl -u autobot-web -f
```

## Обновление

На сервере одной командой: резервная копия, `git pull`, зависимости, проверка
синтаксиса, обновление изменившихся юнитов, перезапуск и проверка, что Web App отвечает.

```bash
sudo /opt/autobot/deploy/update.sh
```

С рабочего компьютера — `deploy.ps1` (PowerShell): останавливается, если ветка
не `main` или есть незакоммиченные изменения, прогоняет тесты, делает `git push`,
запускает `update.sh` по SSH-алиасу `autobot` и проверяет сайт.

```powershell
.\deploy\deploy.ps1
```

`.env`, базы и `uploads/` в Git не попадают и обновлением не затираются.
