#!/bin/bash
set -Eeuo pipefail
umask 077

trap 'status=$?; printf "odoo acceptance failed: line=%s status=%s command=%q\n" "$LINENO" "$status" "$BASH_COMMAND" >&2; exit "$status"' ERR

result=${TKL_TEST_RESULT:?TKL_TEST_RESULT is required}
app_password=${TKL_TEST_APP_PASS:?TKL_TEST_APP_PASS is required}
source_file=/usr/local/share/turnkey-odoo/source
database=TurnkeylinuxExample
test_database=turnkey_v19_acceptance_$$
test_admin_password=$(mcookie)
fixture="TurnKey v19 contact $(date +%s)-$$"
email="odoo-v19-$$@example.invalid"
cron_marker="TKL-v19-cron-$(date +%s)-$$"
work=$(mktemp -d /tmp/odoo-v19.XXXXXXXX)
cookie=$work/cookie
partner_id=
cron_id=

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck source=odoo-auth-diagnostics.sh
. "$script_dir/odoo-auth-diagnostics.sh"

command -v jq >/dev/null

ocurl() {
    curl --insecure --fail --silent --show-error \
        --connect-timeout 5 --max-time 15 \
        --cookie "$cookie" --cookie-jar "$cookie" \
        --header 'Content-Type: application/json' "$@"
}

rpc_result() {
    jq -er '
        if has("error") then
            error(.error.data.message // .error.message // "Odoo RPC failed")
        else
            .result
        end
    '
}

ocall() {
    local model=$1
    local method=$2
    local args=$3
    local kwargs=${4:-'{}'}
    local payload

    payload=$(jq -cn \
        --arg model "$model" \
        --arg method "$method" \
        --argjson args "$args" \
        --argjson kwargs "$kwargs" \
        '{jsonrpc:"2.0", method:"call", params:{model:$model, method:$method, args:$args, kwargs:$kwargs}}')
    ocurl --data "$payload" \
        "https://127.0.0.1/web/dataset/call_kw/$model/$method"
}

cleanup() {
    trap - ERR
    set +e
    if [[ -n $cron_id ]]; then
        ocall ir.cron unlink "$(jq -cn --argjson id "$cron_id" '[[$id]]')" |
            rpc_result >/dev/null
    fi
    if [[ -n $partner_id ]]; then
        ocall res.partner unlink "$(jq -cn --argjson id "$partner_id" '[[$id]]')" |
            rpc_result >/dev/null
    fi
    find "$work" -depth -delete
}
trap cleanup EXIT

for unit in apache2.service postgresql.service odoo.service postfix.service; do
    if ! systemctl --quiet is-active "$unit"; then
        echo "$unit is not active" >&2
        systemctl --no-pager --full status "$unit" >&2 || true
        exit 1
    fi
    if ! systemctl --quiet is-enabled "$unit"; then
        echo "$unit is not enabled" >&2
        systemctl --no-pager --full status "$unit" >&2 || true
        exit 1
    fi
done
apache2ctl configtest
apache_modules=$(apache2ctl -M)
grep -Fq 'proxy_module' <<<"$apache_modules"
grep -Fq 'proxy_http_module' <<<"$apache_modules"
grep -Fq 'proxy_wstunnel_module' <<<"$apache_modules"
grep -Fxq 'VERSION_CODENAME=trixie' /etc/os-release
grep -Eq '^turnkey-odoo-19\.0' /etc/turnkey_version
test "$(stat -c '%U:%G:%a' /etc/odoo/odoo.conf)" = root:odoo:640
test "$(stat -c '%U:%G:%a' "$source_file")" = root:root:644
test -d /usr/share/adminer
for module in apache postgresql postfix; do
    test -d "/usr/share/webmin/$module"
done

runuser -u odoo -- python3 <<'PY'
from odoo.tools import config

config.parse_config(['--config=/etc/odoo/odoo.conf'])
assert config['proxy_mode'] is True
assert config['workers'] == 2
assert config['max_cron_threads'] == 1
assert config['gevent_port'] == 8072
assert config['data_dir'] == '/var/lib/odoo/.local/share/Odoo'
PY
! grep -Fq '/root' /etc/odoo/odoo.conf

service_environment=$(systemctl show odoo.service --property=Environment --value)
[[ $service_environment == *ODOO_NOTIFY_CRON_CHANGES=1* ]]
[[ $service_environment == *HOME=/var/lib/odoo* ]]
service_main_pid=$(systemctl show odoo.service --property=MainPID --value)
[[ $service_main_pid =~ ^[1-9][0-9]*$ ]]
tr '\0' '\n' <"/proc/$service_main_pid/environ" |
    grep -Fxq 'HOME=/var/lib/odoo'

# shellcheck disable=SC1090
. "$source_file"
: "${package_source:?package_source is missing from $source_file}"
: "${installed_version:?installed_version is missing from $source_file}"
: "${package_url:?package_url is missing from $source_file}"
: "${package_sha256:?package_sha256 is missing from $source_file}"
: "${repository_key_fingerprint:?repository_key_fingerprint is missing from $source_file}"
: "${wkhtmltox_version:?wkhtmltox_version is missing from $source_file}"
: "${wkhtmltox_architecture:?wkhtmltox_architecture is missing from $source_file}"
: "${wkhtmltox_url:?wkhtmltox_url is missing from $source_file}"
: "${wkhtmltox_sha256:?wkhtmltox_sha256 is missing from $source_file}"
: "${pypdf_compat_package:?pypdf_compat_package is missing from $source_file}"
: "${pypdf_compat_version:?pypdf_compat_version is missing from $source_file}"
test "$installed_version" = 19.0.20260825
test "$(dpkg-query -W -f='${Version}' odoo)" = "$installed_version"
test "$upstream_package_sha256" = e9d89da0fc94cd752b08b1e5501d97f464b834229ff8d68c7fecf24304e1da69
test -n "$repacked_package_sha256"
test -n "$upstream_payload_sha256"
test "$dependency_rewrite" = \
    python3-pypdf2_to_python3-pypdf2_or_python3-pypdf
test "$(dpkg-query -W -f='${Status}' python3-pypdf)" = \
    'install ok installed'
dpkg-query -W -f='${Depends}' odoo |
    grep -Fq 'python3-pypdf2 | python3-pypdf'
test "$(gpg --show-keys --with-colons /usr/share/keyrings/odoo-archive-keyring.gpg |
    awk -F: '$1 == "fpr" && !fingerprint { fingerprint=$10 } END { print fingerprint }')" = \
    "$repository_key_fingerprint"
grep -Fq 'signed-by=/usr/share/keyrings/odoo-archive-keyring.gpg' \
    /etc/apt/sources.list.d/odoo.list
odoo --version | grep -Fq '19.0'
test "$wkhtmltox_version" = '1:0.12.6.1-3.bookworm'
test "$wkhtmltox_architecture" = amd64
test "$wkhtmltox_url" = https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb
test "$(dpkg-query -W -f='${Version}' wkhtmltox)" = "$wkhtmltox_version"
test "$(dpkg-query -W -f='${Architecture}' wkhtmltox)" = "$wkhtmltox_architecture"
test "$wkhtmltox_sha256" = 98ba0d157b50d36f23bd0dedf4c0aa28c7b0c50fcdcdc54aa5b6bbba81a3941d
wkhtmltopdf --version | grep -Fq 'wkhtmltopdf 0.12.6.1 (with patched qt)'
wkhtmltopdf --quiet - "$work/report.pdf" <<'EOF'
<!doctype html><html><body><p>TurnKey Odoo v19 report probe</p></body></html>
EOF
test "$(head -c 4 "$work/report.pdf")" = '%PDF'
test "$pypdf_compat_package" = turnkey-odoo-pypdf-compat
test "$pypdf_compat_version" = 1.0+turnkey19.0.1
test "$(dpkg-query -W -f='${Version}' "$pypdf_compat_package")" = \
    "$pypdf_compat_version"
test "$(dpkg-query -W -f='${Provides}' "$pypdf_compat_package")" = \
    python3-pypdf2
apt-get check
runuser -u odoo -- python3 <<'PY'
import io

import pypdf
from odoo.tools import pdf as odoo_pdf

assert odoo_pdf.SUBMOD == '._pypdf'
writer = pypdf.PdfWriter()
writer.add_blank_page(width=72, height=72)
stream = io.BytesIO()
writer.write(stream)
stream.seek(0)
assert len(pypdf.PdfReader(stream).pages) == 1
PY

role_state=$(runuser -u postgres -- psql --no-psqlrc --tuples-only \
    --no-align postgres --command="
        SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication
        FROM pg_roles WHERE rolname = 'odoo';")
test "$role_state" = 'f|t|f|f'
database_owner=$(runuser -u postgres -- psql --no-psqlrc --tuples-only \
    --no-align postgres --command="
        SELECT pg_get_userbyid(datdba) FROM pg_database
        WHERE datname = '$database';")
test "$database_owner" = odoo
runuser -u postgres -- psql --no-psqlrc --tuples-only --no-align \
    "$database" --command='SELECT 1 FROM res_users LIMIT 1;' |
    grep -Fxq 1
admin_password_hash=$(runuser -u postgres -- psql --no-psqlrc --tuples-only \
    --no-align "$database" --command="
        SELECT password FROM res_users
        WHERE id = (SELECT res_id FROM ir_model_data
                    WHERE module = 'base' AND name = 'user_admin');")
[[ $admin_password_hash == \$* ]]
[[ $admin_password_hash != "$app_password" ]]

authenticate
test "$(stat -c '%U:%G:%a' /var/lib/odoo/.local/share/Odoo/sessions)" = \
    odoo:odoo:700

contact_args=$(jq -cn --arg name "$fixture" --arg email "$email" \
    '[{name:$name, email:$email}]')
partner_id=$(ocall res.partner create "$contact_args" | rpc_result)
[[ $partner_id =~ ^[0-9]+$ ]]

contact_domain=$(jq -cn --argjson id "$partner_id" '[[["id","=",$id]]]')
contact_fields='{"fields":["id","name","email","phone"]}'
readback=$(ocall res.partner search_read "$contact_domain" "$contact_fields" |
    rpc_result)
jq -e --arg name "$fixture" --arg email "$email" \
    '.[0].name == $name and .[0].email == $email' <<<"$readback" >/dev/null
runuser -u postgres -- psql --no-psqlrc --tuples-only --no-align \
    "$database" --command="SELECT name FROM res_partner WHERE id = $partner_id;" |
    grep -Fxq "$fixture"

systemctl restart postgresql.service
systemctl restart odoo.service
ready=
for attempt in {1..60}; do
    if authenticate quiet >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 2
done
if [[ $ready != 1 ]]; then
    authenticate diagnose || true
fi
test "$ready" = 1

main_pid=$(systemctl show odoo.service --property=MainPID --value)
[[ $main_pid =~ ^[1-9][0-9]*$ ]]
worker_processes=$(ps --no-headers --ppid "$main_pid" -o pid= | awk 'END { print NR }')
(( worker_processes >= 4 ))

runuser -u postgres -- psql --no-psqlrc --tuples-only --no-align \
    "$database" --command="SELECT name FROM res_partner WHERE id = $partner_id;" |
    grep -Fxq "$fixture"

model_domain='[[["model","=","res.partner"]]]'
model_id=$(ocall ir.model search_read "$model_domain" \
    '{"fields":["id"],"limit":1}' | rpc_result | jq -er '.[0].id')
cron_code="model.browse($partner_id).write({'phone': '$cron_marker'})"
cron_args=$(jq -cn \
    --arg name "TurnKey v19 cron $partner_id" \
    --arg code "$cron_code" \
    --arg nextcall "$(date -u '+%Y-%m-%d %H:%M:%S')" \
    --argjson model_id "$model_id" \
    '[{name:$name, model_id:$model_id, state:"code", code:$code, interval_number:1, interval_type:"months", nextcall:$nextcall}]')
cron_id=$(ocall ir.cron create "$cron_args" | rpc_result)
[[ $cron_id =~ ^[0-9]+$ ]]

cron_complete=
for attempt in {1..60}; do
    readback=$(ocall res.partner search_read "$contact_domain" "$contact_fields" |
        rpc_result)
    if jq -e --arg marker "$cron_marker" \
            '.[0].phone == $marker' <<<"$readback" >/dev/null; then
        cron_complete=1
        break
    fi
    sleep 2
done
test "$cron_complete" = 1

printf '%s\n' "$app_password" | runuser -u odoo -- python3 -c \
    'import sys; from odoo.tools import config; config.parse_config(["--config=/etc/odoo/odoo.conf"]); assert config.verify_admin_password(sys.stdin.readline().rstrip("\n"))'

odoo-update --check >"$work/update"
candidate=$(sed -n 's/^candidate=//p' "$work/update")
status=$(sed -n 's/^status=//p' "$work/update")
test -n "$candidate"
grep -Fxq 'channel=official-odoo-19-community-daily' "$work/update"
grep -Fxq "integrity=APT-signed-by-$repository_key_fingerprint" "$work/update"
grep -Fxq "renderer=wkhtmltox-$wkhtmltox_version" "$work/update"
grep -Fxq "renderer_architecture=$wkhtmltox_architecture" "$work/update"
grep -Fxq 'renderer_policy=pinned-manual-security-review' "$work/update"
grep -Fxq "renderer_integrity=SHA256-$wkhtmltox_sha256" "$work/update"
grep -Fxq "dependency_bridge=$pypdf_compat_package-$pypdf_compat_version" \
    "$work/update"
grep -Fxq 'dependency_bridge_provides=python3-pypdf2' "$work/update"
grep -Eq '^pypdf=python3-pypdf-.+' "$work/update"
grep -Fxq 'candidate_resolution=apt-simulated' "$work/update"

cat >"$result" <<EOF
package_source=Official Odoo 19 Community daily Debian repository
installed_version=$installed_version
runtime_checks=normal init; Apache HTTPS admin login; contact create and JSON/PostgreSQL readback; supervised PostgreSQL/Odoo restart; two HTTP workers and a real cron-worker record update; patched wkhtmltopdf PDF render; database master password; Adminer and Webmin modules; Postfix
updater_command=odoo-update --check
updater_result=$status; candidate=$candidate; dependency resolution simulated; renderer=$wkhtmltox_version pinned for manual security review
updater_channel=official Odoo 19 Community daily packages
integrity_evidence=repository key $repository_key_fingerprint; Odoo package SHA-256 $package_sha256; wkhtmltox package SHA-256 $wkhtmltox_sha256; pypdf compatibility provider $pypdf_compat_package $pypdf_compat_version
EOF
