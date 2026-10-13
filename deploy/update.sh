#!/usr/bin/env bash
# Обновление кода на сервере одной командой: sudo /opt/autobot/deploy/update.sh
set -Eeuo pipefail

app_dir="/opt/autobot"
app_user="admin"
services=(
    autobot-web
    autobot-main
    autobot-telegram
    autobot-webapp-bot
    autobot-hybrid
)

if [[ $EUID -ne 0 ]]; then
    echo "Запускать через sudo: sudo $app_dir/deploy/update.sh" >&2
    exit 1
fi

cd "$app_dir"

echo "==> Резервная копия перед обновлением"
bash "$app_dir/deploy/backup.sh"

echo "==> Получение изменений"
sudo -u "$app_user" git -C "$app_dir" pull --ff-only

echo "==> Зависимости"
sudo -u "$app_user" "$app_dir/venv/bin/pip" install --quiet -r "$app_dir/requirements.txt"

echo "==> Проверка синтаксиса"
sudo -u "$app_user" "$app_dir/venv/bin/python" -m compileall -q \
    showcase_bot showcase_telegram_bot showcase_webapp_bot showcase_hybrid_bot

echo "==> Юниты systemd"
# Юниты лежат в репозитории: изменённые копируются, иначе правка в
# deploy/systemd/ не доехала бы до сервера.
units_changed=0
for unit in "$app_dir"/deploy/systemd/*.service "$app_dir"/deploy/systemd/*.timer; do
    target="/etc/systemd/system/$(basename "$unit")"
    if ! cmp -s "$unit" "$target"; then
        install -m 644 "$unit" "$target"
        echo "обновлён $(basename "$unit")"
        units_changed=1
    fi
done
if [[ $units_changed -eq 1 ]]; then
    systemctl daemon-reload
fi

echo "==> Перезапуск сервисов"
systemctl restart "${services[@]}"

echo "==> Web App отвечает локально"
for attempt in $(seq 10); do
    if curl --fail --silent --max-time 5 -o /dev/null http://127.0.0.1:8000/; then
        break
    fi
    if [[ $attempt -eq 10 ]]; then
        echo "Web App не ответил после перезапуска" >&2
        systemctl status autobot-web --no-pager >&2 || true
        exit 1
    fi
    sleep 2
done

systemctl is-active "${services[@]}"
echo "Обновление завершено."
