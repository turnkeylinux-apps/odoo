#!/bin/bash

# Diagnostic support for the Odoo authentication acceptance boundary. The
# caller owns `work`, `cookie`, `database`, and `app_password`.

auth_proxy_url=${auth_proxy_url:-https://127.0.0.1/web/session/authenticate}
auth_direct_url=${auth_direct_url:-http://127.0.0.1:8069/web/session/authenticate}
if ! declare -p auth_log_files >/dev/null 2>&1; then
    auth_log_files=(
        /var/log/odoo/odoo-server.log
        /var/log/apache2/access.log
        /var/log/apache2/error.log
    )
fi

sanitize_auth_diagnostic() {
    APP_SECRET=$app_password perl -pe '
        BEGIN { $secret = $ENV{"APP_SECRET"} // ""; }
        s/\Q$secret\E/[REDACTED]/g if length $secret;
        s/^(Set-Cookie:\s*)[^;]*/${1}[REDACTED]/i;
        s/(session_id=)[^;\s"]+/${1}[REDACTED]/ig;
    '
}

capture_auth_response() {
    local name=$1
    local url=$2
    local payload=$3
    local -n http_status_ref=$4
    local -n curl_status_ref=$5
    local response_cookie=$cookie
    local prefix=$work/auth-$name

    if [[ $name == direct ]]; then
        response_cookie=$work/direct-cookie
    fi

    if http_status_ref=$(curl --insecure --silent --show-error \
            --max-time 30 \
            --cookie "$response_cookie" --cookie-jar "$response_cookie" \
            --header 'Content-Type: application/json' \
            --dump-header "$prefix.headers" \
            --output "$prefix.body" \
            --stderr "$prefix.curl-error" \
            --write-out '%{http_code}' \
            --data "$payload" "$url"); then
        curl_status_ref=0
    else
        curl_status_ref=$?
    fi
}

print_auth_file() {
    local label=$1
    local file=$2

    printf '%s\n' "--- $label ---"
    if [[ -r $file ]]; then
        sanitize_auth_diagnostic <"$file"
    else
        printf 'unavailable: %s\n' "$file"
    fi
}

print_auth_response() {
    local name=$1
    local curl_status=$2
    local http_status=$3
    local prefix=$work/auth-$name

    printf 'auth_probe=%s curl_status=%s http_status=%s\n' \
        "$name" "$curl_status" "${http_status:-absent}"
    print_auth_file "$name response headers" "$prefix.headers"
    print_auth_file "$name response body" "$prefix.body"
    print_auth_file "$name curl stderr" "$prefix.curl-error"
}

print_auth_logs() {
    local logfile

    for logfile in "${auth_log_files[@]}"; do
        printf '%s\n' "--- log tail: $logfile ---"
        if [[ -r $logfile ]]; then
            if ! tail -n 240 "$logfile" 2>&1 | sanitize_auth_diagnostic; then
                printf 'unable to read complete log tail: %s\n' "$logfile"
            fi
        else
            printf 'unavailable: %s\n' "$logfile"
        fi
    done
}

authenticate() {
    local diagnostics=${1:-diagnose}
    local payload proxy_http_status= proxy_curl_status=
    local direct_http_status= direct_curl_status=

    payload=$(jq -cn \
        --arg db "$database" \
        --arg login admin \
        --arg password "$app_password" \
        '{jsonrpc:"2.0", method:"call", params:{db:$db, login:$login, password:$password}}')
    capture_auth_response proxy "$auth_proxy_url" "$payload" \
        proxy_http_status proxy_curl_status

    if (( proxy_curl_status == 0 )) && [[ $proxy_http_status == 200 ]] &&
            jq -e '.result.uid == 2 and (.error | not)' \
                "$work/auth-proxy.body" >/dev/null; then
        return 0
    fi

    if [[ $diagnostics == diagnose ]]; then
        print_auth_response proxy "$proxy_curl_status" "$proxy_http_status"
        capture_auth_response direct "$auth_direct_url" "$payload" \
            direct_http_status direct_curl_status
        print_auth_response direct "$direct_curl_status" "$direct_http_status"
        print_auth_logs
    fi
    return 1
}
