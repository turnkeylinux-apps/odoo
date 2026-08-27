#!/bin/bash
set -Eeuo pipefail

repo_root=$(cd "$(dirname "$0")/.." && pwd -P)
fixture_root=$(mktemp -d /tmp/odoo-auth-diagnostics.XXXXXXXX)
trap 'find "$fixture_root" -depth -delete' EXIT
mkdir -p "$fixture_root/bin" "$fixture_root/work"

app_password='fixture password with spaces and $pecial characters'
database=TurnkeylinuxExample
work=$fixture_root/work
cookie=$work/cookie
auth_proxy_url=https://proxy.invalid/web/session/authenticate
auth_direct_url=http://127.0.0.1:8069/web/session/authenticate
auth_log_files=(
    "$fixture_root/odoo-server.log"
    "$fixture_root/apache-access.log"
    "$fixture_root/apache-error.log"
)

cat >"$fixture_root/bin/curl" <<'EOF'
#!/bin/bash
set -Eeuo pipefail

headers=
body=
stderr=
payload=
url=
while (($#)); do
    case $1 in
        --dump-header)
            headers=$2
            shift 2
            ;;
        --output)
            body=$2
            shift 2
            ;;
        --stderr)
            stderr=$2
            shift 2
            ;;
        --data)
            payload=$2
            shift 2
            ;;
        --cookie|--cookie-jar|--header|--max-time|--write-out)
            shift 2
            ;;
        --insecure|--silent|--show-error)
            shift
            ;;
        *)
            url=$1
            shift
            ;;
    esac
done

printf '%s\t%s\n' "$url" "$payload" >>"$FIXTURE_CALLS"
: >"$stderr"
if [[ $url == https://* ]]; then
    printf 'HTTP/1.1 %s Fixture\r\nSet-Cookie: session_id=fixture-session-secret; HttpOnly\r\n\r\n' \
        "${FIXTURE_PROXY_STATUS:-500}" >"$headers"
    if [[ -v FIXTURE_PROXY_BODY ]]; then
        printf '%s' "$FIXTURE_PROXY_BODY" >"$body"
    else
        printf '{"error":{"data":{"debug":"password=%s"}}}' \
            "$FIXTURE_SECRET" >"$body"
    fi
    printf '%s' "${FIXTURE_PROXY_STATUS:-500}"
    exit "${FIXTURE_PROXY_CURL_STATUS:-0}"
fi

printf 'HTTP/1.1 %s Fixture\r\nSet-Cookie: session_id=direct-session-secret; HttpOnly\r\n\r\n' \
    "${FIXTURE_DIRECT_STATUS:-200}" >"$headers"
if [[ -v FIXTURE_DIRECT_BODY ]]; then
    printf '%s' "$FIXTURE_DIRECT_BODY" >"$body"
else
    printf '%s' '{"result":{"uid":2}}' >"$body"
fi
printf '%s' "${FIXTURE_DIRECT_STATUS:-200}"
exit "${FIXTURE_DIRECT_CURL_STATUS:-0}"
EOF
chmod 0755 "$fixture_root/bin/curl"

printf 'Odoo traceback containing %s\n' "$app_password" >"${auth_log_files[0]}"
printf 'proxy access fixture\n' >"${auth_log_files[1]}"
printf 'proxy error fixture\n' >"${auth_log_files[2]}"

# shellcheck source=odoo-auth-diagnostics.sh
. "$repo_root/tests/odoo-auth-diagnostics.sh"

export FIXTURE_CALLS=$fixture_root/calls
export FIXTURE_SECRET=$app_password
export PATH="$fixture_root/bin:/usr/bin:/bin"

if authenticate diagnose >"$fixture_root/failure.out" 2>&1; then
    echo 'proxy HTTP 500 unexpectedly authenticated' >&2
    exit 1
fi
grep -Fxq 'auth_probe=proxy curl_status=0 http_status=500' "$fixture_root/failure.out"
grep -Fxq 'auth_probe=direct curl_status=0 http_status=200' "$fixture_root/failure.out"
grep -Fq -- '--- proxy response headers ---' "$fixture_root/failure.out"
grep -Fq -- '--- direct response body ---' "$fixture_root/failure.out"
grep -Fq -- '--- log tail:' "$fixture_root/failure.out"
grep -Fq '"result":{"uid":2}' "$fixture_root/failure.out"
grep -Fq 'Set-Cookie: [REDACTED]; HttpOnly' "$fixture_root/failure.out"
grep -Fq 'Odoo traceback containing [REDACTED]' "$fixture_root/failure.out"
! grep -Fq "$app_password" "$fixture_root/failure.out"
! grep -Fq 'fixture-session-secret' "$fixture_root/failure.out"
grep -Fq "$app_password" "$work/auth-proxy.body"
grep -Fq 'fixture-session-secret' "$work/auth-proxy.headers"
test "$(wc -l <"$fixture_root/calls")" -eq 2
test "$(cut -f2 "$fixture_root/calls" | sort -u | wc -l)" -eq 1

rm -f "$fixture_root/calls"
rm -f "$work"/auth-* "$work"/cookie "$work"/direct-cookie
FIXTURE_PROXY_STATUS=200 \
FIXTURE_PROXY_BODY='{"result":{"uid":2}}' \
    authenticate diagnose >"$fixture_root/success.out" 2>&1
test "$(wc -l <"$fixture_root/calls")" -eq 1
grep -Fq 'https://proxy.invalid/web/session/authenticate' "$fixture_root/calls"
! grep -Fq '127.0.0.1:8069' "$fixture_root/calls"
test ! -s "$fixture_root/success.out"

echo 'odoo auth diagnostics fixture: PASS'
