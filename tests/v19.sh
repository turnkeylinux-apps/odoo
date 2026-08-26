#!/bin/bash
set -Eeuo pipefail
umask 077

result=${TKL_TEST_RESULT:?TKL_TEST_RESULT is required}
app_password=${TKL_TEST_APP_PASS:?TKL_TEST_APP_PASS is required}
source_file=/usr/local/share/turnkey-odoo/source
database=TurnkeylinuxExample
test_database=turnkey_v19_acceptance_$$
test_admin_password=$(mcookie)
fixture="TurnKey v19 contact $(date +%s)-$$"
email="odoo-v19-$$@example.invalid"
work=$(mktemp -d /tmp/odoo-v19.XXXXXXXX)
cookie=$work/cookie
partner_id=
test_database_created=

ocurl() {
    curl --insecure --fail --silent --show-error \
        --connect-timeout 5 --max-time 15 \
        --cookie "$cookie" --cookie-jar "$cookie" \
        --header 'Content-Type: application/json' "$@"
}

cleanup() {
    set +e
    if [[ -n $test_database_created ]]; then
        runuser -u odoo -- odoo db -c /etc/odoo/odoo.conf \
            drop "$test_database" >/dev/null
    fi
    if [[ -n $partner_id ]]; then
        ocurl --data "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"model\":\"res.partner\",\"method\":\"unlink\",\"args\":[[$partner_id]],\"kwargs\":{}}}" \
            https://127.0.0.1/web/dataset/call_kw/res.partner/unlink >/dev/null
    fi
    find "$work" -depth -delete
}
trap cleanup EXIT

for unit in apache2.service postgresql.service odoo.service postfix.service; do
    systemctl --quiet is-active "$unit"
    systemctl --quiet is-enabled "$unit"
done
apache2ctl configtest
grep -Fq 'ProxyPass /websocket ws://127.0.0.1:8072/websocket' \
    /etc/apache2/sites-enabled/odoo.conf
grep -Fxq 'VERSION_CODENAME=trixie' /etc/os-release
grep -Eq '^turnkey-odoo-19\.0' /etc/turnkey_version
test "$(stat -c '%U:%G:%a' /etc/odoo/odoo.conf)" = root:odoo:640
test -d /usr/share/adminer
for module in apache postgresql postfix; do
    test -d "/usr/share/webmin/$module"
done

# shellcheck disable=SC1090
. "$source_file"
test "$installed_version" = 19.0.20260825
test "$(dpkg-query -W -f='${Version}' odoo)" = "$installed_version"
test "$package_sha256" = e9d89da0fc94cd752b08b1e5501d97f464b834229ff8d68c7fecf24304e1da69
test "$(gpg --show-keys --with-colons /usr/share/keyrings/odoo-archive-keyring.gpg |
    awk -F: '$1 == "fpr" { print $10; exit }')" = \
    "$repository_key_fingerprint"
odoo --version | grep -Fq '19.0'
runuser -u odoo -- python3 - <<'PY'
import odoo

odoo.tools.config.parse_config(['--config=/etc/odoo/odoo.conf'])
assert odoo.tools.config['proxy_mode'] is True
assert odoo.tools.config['workers'] > 0
assert odoo.tools.config['gevent_port'] == 8072
PY
ss -ltn | awk '$4 ~ /:8072$/ { found = 1 } END { exit !found }'

test_database_created=1
test "$test_admin_password" != admin
runuser -u odoo -- odoo db -c /etc/odoo/odoo.conf init \
    "$test_database" --password "$test_admin_password"
database_evidence=$(su postgres -c \
    "psql --tuples-only --no-align '$test_database'" <<'EOF'
SELECT name || ':' || state FROM ir_module_module WHERE name = 'base';
SELECT login FROM res_users WHERE id = 2;
EOF
)
grep -Fxq 'base:installed' <<<"$database_evidence"
grep -Fxq 'admin' <<<"$database_evidence"
printf '%s\n' "$test_admin_password" | runuser -u odoo -- \
    python3 -c '
import sys

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.tools import config

database = sys.argv[1]
password = sys.stdin.readline().rstrip("\n")
config.parse_config(["--config=/etc/odoo/odoo.conf"])
with Registry(database).cursor() as cursor:
    environment = api.Environment(cursor, SUPERUSER_ID, {})
    authentication = environment["res.users"].authenticate(
        {"login": "admin", "password": password, "type": "password"},
        {"interactive": False},
    )
    assert authentication["uid"] == 2
' "$test_database"
runuser -u odoo -- odoo db -c /etc/odoo/odoo.conf drop "$test_database"
test_database_created=
test "$(su postgres -c "psql --tuples-only --no-align postgres" <<EOF
SELECT count(*) FROM pg_database WHERE datname = '$test_database';
EOF
)" = 0

auth=$(ocurl --data "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"db\":\"$database\",\"login\":\"admin\",\"password\":\"$app_password\"}}" \
    https://127.0.0.1/web/session/authenticate)
jq -e '.result.uid == 2' <<<"$auth" >/dev/null

created=$(ocurl --data "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"model\":\"res.partner\",\"method\":\"create\",\"args\":[{\"name\":\"$fixture\",\"email\":\"$email\"}],\"kwargs\":{}}}" \
    https://127.0.0.1/web/dataset/call_kw/res.partner/create)
partner_id=$(jq -er '.result' <<<"$created")
[[ $partner_id =~ ^[0-9]+$ ]]

readback=$(ocurl --data "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"model\":\"res.partner\",\"method\":\"search_read\",\"args\":[[[\"id\",\"=\",$partner_id]]],\"kwargs\":{\"fields\":[\"id\",\"name\",\"email\"]}}}" \
    https://127.0.0.1/web/dataset/call_kw/res.partner/search_read)
jq -e --arg name "$fixture" --arg email "$email" \
    '.result[0].name == $name and .result[0].email == $email' \
    <<<"$readback" >/dev/null
su postgres -c "psql --tuples-only --no-align '$database'" <<EOF |
SELECT name FROM res_partner WHERE id = $partner_id;
EOF
    grep -Fxq "$fixture"

systemctl restart postgresql.service odoo.service
restart_auth=
for attempt in {1..60}; do
    if candidate_auth=$(ocurl --data "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"db\":\"$database\",\"login\":\"admin\",\"password\":\"$app_password\"}}" \
        https://127.0.0.1/web/session/authenticate 2>/dev/null) && \
            jq -e '.result.uid == 2' <<<"$candidate_auth" >/dev/null; then
        restart_auth=$candidate_auth
        break
    fi
    sleep 2
done
test -n "$restart_auth"
restart_readback=$(ocurl --data "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"model\":\"res.partner\",\"method\":\"search_read\",\"args\":[[[\"id\",\"=\",$partner_id]]],\"kwargs\":{\"fields\":[\"id\",\"name\",\"email\"]}}}" \
    https://127.0.0.1/web/dataset/call_kw/res.partner/search_read)
jq -e --arg name "$fixture" --arg email "$email" \
    '.result[0].name == $name and .result[0].email == $email' \
    <<<"$restart_readback" >/dev/null
su postgres -c "psql --tuples-only --no-align '$database'" <<EOF |
SELECT name FROM res_partner WHERE id = $partner_id;
EOF
    grep -Fxq "$fixture"

printf '%s\n' "$app_password" | runuser -u odoo -- python3 -c \
    'import sys; import odoo; odoo.tools.config.parse_config(["--config=/etc/odoo/odoo.conf"]); assert odoo.tools.config.verify_admin_password(sys.stdin.readline().rstrip("\n"))'

odoo-update --check >"$work/update"
candidate=$(sed -n 's/^candidate=//p' "$work/update")
status=$(sed -n 's/^status=//p' "$work/update")
test -n "$candidate"
grep -Fxq 'channel=official-odoo-19-community-daily' "$work/update"
grep -Fxq "integrity=APT-signed-by-$repository_key_fingerprint" "$work/update"

cat >"$result" <<EOF
package_source=Official Odoo 19 Community daily Debian repository
installed_version=$installed_version
runtime_checks=multiprocess proxy and websocket port; supported database create, initialize, verify, and remove; normal init; HTTPS admin login; contact create and JSON readback; PostgreSQL and API restart persistence; database master password; Adminer and Webmin modules; Postfix
updater_command=odoo-update --check
updater_result=$status; candidate=$candidate
updater_channel=official Odoo 19 Community daily packages
integrity_evidence=repository key $repository_key_fingerprint; package SHA-256 $package_sha256
EOF
