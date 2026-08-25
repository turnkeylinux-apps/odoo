#!/bin/bash
set -Eeuo pipefail
umask 077

result=${TKL_TEST_RESULT:?TKL_TEST_RESULT is required}
app_password=${TKL_TEST_APP_PASS:?TKL_TEST_APP_PASS is required}
source_file=/usr/local/share/turnkey-odoo/source
database=TurnkeylinuxExample
fixture="TurnKey v19 contact $(date +%s)-$$"
email="odoo-v19-$$@example.invalid"
work=$(mktemp -d /tmp/odoo-v19.XXXXXXXX)
cookie=$work/cookie
partner_id=

ocurl() {
    curl --insecure --fail --silent --show-error \
        --cookie "$cookie" --cookie-jar "$cookie" \
        --header 'Content-Type: application/json' "$@"
}

cleanup() {
    set +e
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
for attempt in {1..60}; do
    ocurl --data "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"db\":\"$database\",\"login\":\"admin\",\"password\":\"$app_password\"}}" \
        https://127.0.0.1/web/session/authenticate >/dev/null 2>&1 && break
    sleep 2
done
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
runtime_checks=normal init; HTTPS admin login; contact create and JSON readback; PostgreSQL readback; restart persistence; database master password; Adminer and Webmin modules; Postfix
updater_command=odoo-update --check
updater_result=$status; candidate=$candidate
updater_channel=official Odoo 19 Community daily packages
integrity_evidence=repository key $repository_key_fingerprint; package SHA-256 $package_sha256
EOF
