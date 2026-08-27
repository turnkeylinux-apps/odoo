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

active=$fixture/active.conf
cat >"$active" <<'EOF'
[options]
admin_passwd = active default
db_password = False
EOF
printf 'db_password=%s\nadmin_passwd=%s\n' \
    "$db_secret" "$master_secret" | "$helper" "$active"
grep -Fxq "admin_passwd = $master_secret" "$active"
grep -Fxq "db_password = $db_secret" "$active"

commented_db=$fixture/commented-db.conf
cat >"$commented_db" <<'EOF'
[options]
admin_passwd = active default
; db_password = False
EOF
cp "$commented_db" "$commented_db.before"
if printf 'db_password=%s\nadmin_passwd=%s\n' \
        "$db_secret" "$master_secret" |
        "$helper" "$commented_db" >"$fixture/commented-db.stdout" \
            2>"$fixture/commented-db.stderr"; then
    echo 'commented db_password unexpectedly accepted' >&2
    exit 1
fi
grep -Fxq 'missing Odoo secret setting: db_password' \
    "$fixture/commented-db.stderr"
cmp "$commented_db.before" "$commented_db"

for near_miss in \
        ';admin_passwd = admin' \
        '; admin_passwd=admin' \
        '; admin_passwd = changed' \
        ' ; admin_passwd = admin'; do
    near_miss_config=$fixture/near-miss.conf
    printf '[options]\n%s\ndb_password = False\n' "$near_miss" \
        >"$near_miss_config"
    cp "$near_miss_config" "$near_miss_config.before"
    if printf 'db_password=%s\nadmin_passwd=%s\n' \
            "$db_secret" "$master_secret" |
            "$helper" "$near_miss_config" >"$fixture/near-miss.stdout" \
                2>"$fixture/near-miss.stderr"; then
        echo "near-miss admin_passwd unexpectedly accepted: $near_miss" >&2
        exit 1
    fi
    grep -Fxq 'missing Odoo secret setting: admin_passwd' \
        "$fixture/near-miss.stderr"
    cmp "$near_miss_config.before" "$near_miss_config"
done

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
