#!/usr/bin/env bash
set -Eeuo pipefail

app_dir="/opt/autobot"
backup_dir="/var/backups/autobot"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"

install -d -m 0700 "$backup_dir"

while IFS= read -r -d '' database; do
    relative_path="${database#"$app_dir"/}"
    backup_name="${relative_path//\//_}.${timestamp}.db"
    sqlite3 "$database" ".timeout 5000" ".backup '$backup_dir/$backup_name'"
done < <(find "$app_dir" -maxdepth 2 -type f -name '*.db' -print0)

uploads_dir="$app_dir/showcase_webapp_bot/uploads"
if [[ -d "$uploads_dir" ]]; then
    tar -C "$app_dir/showcase_webapp_bot" -czf "$backup_dir/uploads.${timestamp}.tar.gz" uploads
fi

find "$backup_dir" -type f -mtime +14 -delete
