#!/bin/bash
set -Eeuo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
helper=$root/overlay/usr/local/sbin/odoo-set-config-secrets
fixture=$(mktemp -d)
trap 'find "$fixture" -depth -delete' EXIT

config=$fixture/odoo.conf
input=$fixture/input
db_secret='db&secret|with\slashes=and equals'
master_secret='master&secret|with\slashes=and equals'
cat >"$config" <<'EOF'
[options]
db_password = old database secret
admin_passwd = old master secret
db_host = localhost
EOF
mkfifo "$input"

# Hold the FIFO's write end open so the process can be inspected while it
# waits for records.
"$helper" "$config" <"$input" &
helper_pid=$!
exec 3>"$input"
for _ in {1..50}; do
    if tr '\0' '\n' <"/proc/$helper_pid/cmdline" | grep -Fxq "$helper"; then
        break
    fi
    sleep 0.01
done
argv=$(tr '\0' '\n' <"/proc/$helper_pid/cmdline")
grep -Fxq "$helper" <<<"$argv"
! grep -Fq "$db_secret" <<<"$argv"
! grep -Fq "$master_secret" <<<"$argv"

printf 'db_password=%s\nadmin_passwd=%s\n' \
    "$db_secret" "$master_secret" >&3
exec 3>&-
wait "$helper_pid"

grep -Fxq "db_password = $db_secret" "$config"
grep -Fxq "admin_passwd = $master_secret" "$config"
grep -Fxq 'db_host = localhost' "$config"

python3 - "$helper" <<'PY'
import ast
import pathlib
import sys

ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
PY

bash -n "$root/conf.d/main"
bash -n "$root/overlay/usr/lib/inithooks/firstboot.d/20-odoo-db-secrets"
bash -n "$root/tests/v19.sh"
! grep -E 'sed .*\$(DB_PASS|ODOO_ADMIN_PASSWORD)' \
    "$root/conf.d/main" \
    "$root/overlay/usr/lib/inithooks/firstboot.d/20-odoo-db-secrets"
git -C "$root" diff --check
