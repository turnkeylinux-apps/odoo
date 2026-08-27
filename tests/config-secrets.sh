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
; This is the password that allows database operations:
; admin_passwd = admin
db_host = False
db_port = False
db_user = odoo
db_password = False
;addons_path = /usr/lib/python3/dist-packages/odoo/addons
default_productivity_apps = True
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
test "$(grep -Fxc "admin_passwd = $master_secret" "$config")" -eq 1
test "$(grep -Fxc "db_password = $db_secret" "$config")" -eq 1
! grep -Fxq '; admin_passwd = admin' "$config"
! grep -Fxq 'admin_passwd = admin' "$config"
! grep -Fxq 'db_password = False' "$config"
grep -Fxq '; This is the password that allows database operations:' "$config"
grep -Fxq 'db_host = False' "$config"
grep -Fxq 'db_port = False' "$config"
grep -Fxq 'db_user = odoo' "$config"
grep -Fxq ';addons_path = /usr/lib/python3/dist-packages/odoo/addons' "$config"
grep -Fxq 'default_productivity_apps = True' "$config"

missing=$fixture/missing.conf
cat >"$missing" <<'EOF'
[options]
db_password = False
db_host = False
EOF
cp "$missing" "$missing.before"
if printf 'db_password=%s\nadmin_passwd=%s\n' \
        "$db_secret" "$master_secret" |
        "$helper" "$missing" >"$fixture/missing.stdout" 2>"$fixture/missing.stderr"; then
    echo 'missing setting unexpectedly accepted' >&2
    exit 1
fi
grep -Fxq 'missing Odoo secret setting: admin_passwd' "$fixture/missing.stderr"
cmp "$missing.before" "$missing"

duplicate=$fixture/duplicate.conf
cat >"$duplicate" <<'EOF'
[options]
; admin_passwd = admin
admin_passwd = another default
db_password = False
EOF
cp "$duplicate" "$duplicate.before"
if printf 'db_password=%s\nadmin_passwd=%s\n' \
        "$db_secret" "$master_secret" |
        "$helper" "$duplicate" >"$fixture/duplicate.stdout" 2>"$fixture/duplicate.stderr"; then
    echo 'duplicate setting unexpectedly accepted' >&2
    exit 1
fi
grep -Fxq 'duplicate Odoo secret setting: admin_passwd' "$fixture/duplicate.stderr"
cmp "$duplicate.before" "$duplicate"

cp "$config" "$config.before-invalid-input"
if printf 'db_password=%s\ndb_password=%s\nadmin_passwd=%s\n' \
        first second "$master_secret" |
        "$helper" "$config" >"$fixture/input-duplicate.stdout" 2>"$fixture/input-duplicate.stderr"; then
    echo 'duplicate input unexpectedly accepted' >&2
    exit 1
fi
grep -Fxq "invalid Odoo secret setting: 'db_password'" \
    "$fixture/input-duplicate.stderr"
cmp "$config.before-invalid-input" "$config"

if printf 'db_password=%s\nadmin_passwd=%s\nunknown=%s\n' \
        "$db_secret" "$master_secret" value |
        "$helper" "$config" >"$fixture/input-unknown.stdout" 2>"$fixture/input-unknown.stderr"; then
    echo 'unknown input unexpectedly accepted' >&2
    exit 1
fi
grep -Fxq "invalid Odoo secret setting: 'unknown'" \
    "$fixture/input-unknown.stderr"
cmp "$config.before-invalid-input" "$config"

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
