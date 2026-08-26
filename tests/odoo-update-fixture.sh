#!/bin/bash
set -Eeuo pipefail

repo_root=$(cd "$(dirname "$0")/.." && pwd -P)
work=$(mktemp -d /tmp/odoo-update-fixture.XXXXXXXX)
trap 'find "$work" -depth -delete' EXIT
mkdir -p "$work/bin"

cat >"$work/source" <<'EOF'
installed_version=19.0.20260825
repository_key_fingerprint=5D134C924CB06330DCEFE2A1DEF2A2198183CBB5
wkhtmltox_version=1:0.12.6.1-3.bookworm
wkhtmltox_architecture=amd64
wkhtmltox_sha256=98ba0d157b50d36f23bd0dedf4c0aa28c7b0c50fcdcdc54aa5b6bbba81a3941d
EOF
cat >"$work/odoo.list" <<'EOF'
deb [signed-by=/usr/share/keyrings/odoo-archive-keyring.gpg] https://nightly.odoo.com/19.0/nightly/deb/ ./
EOF
touch "$work/keyring"

cat >"$work/bin/dpkg-query" <<'EOF'
#!/bin/bash
if [[ $* == *wkhtmltox* ]]; then
    if [[ $* == *Architecture* ]]; then
        printf '%s' "${FIXTURE_RENDERER_ARCHITECTURE:-amd64}"
    else
        printf '%s' "${FIXTURE_RENDERER:-1:0.12.6.1-3.bookworm}"
    fi
else
    printf '%s' "${FIXTURE_INSTALLED:-19.0.20260825}"
fi
EOF
cat >"$work/bin/apt-cache" <<'EOF'
#!/bin/bash
printf 'odoo:\n  Installed: %s\n  Candidate: %s\n' \
    "${FIXTURE_INSTALLED:-19.0.20260825}" \
    "${FIXTURE_CANDIDATE-19.0.20260825}"
awk -v lines="${FIXTURE_TRAILER_LINES:-0}" \
    'BEGIN { for (i = 0; i < lines; i++) print "  fixture-source " i }'
EOF
cat >"$work/bin/gpg" <<'EOF'
#!/bin/bash
printf 'fpr:::::::::%s:\n' \
    "${FIXTURE_FINGERPRINT:-5D134C924CB06330DCEFE2A1DEF2A2198183CBB5}"
printf 'fpr:::::::::ABA924A9766870116E97090D78958C39ADE51428:\n'
EOF
cat >"$work/bin/dpkg" <<'EOF'
#!/bin/bash
exec /usr/bin/dpkg "$@"
EOF
chmod 0755 "$work/bin/"*

sed \
    -e "s|^source_record=.*|source_record=$work/source|" \
    -e "s|^keyring=.*|keyring=$work/keyring|" \
    -e "s|    /etc/apt/sources.list.d/odoo.list|    $work/odoo.list|" \
    "$repo_root/overlay/usr/local/sbin/odoo-update" >"$work/odoo-update"
chmod 0755 "$work/odoo-update"

run_check() {
    env PATH="$work/bin:/usr/bin:/bin" "$@" "$work/odoo-update" --check
}

expect_failure() {
    local name=$1
    shift

    if run_check "$@" >"$work/$name.out" 2>"$work/$name.err"; then
        echo "$name unexpectedly passed" >&2
        exit 1
    fi
}

if env PATH="$work/bin:/usr/bin:/bin" "$work/odoo-update" \
        >"$work/usage.out" 2>"$work/usage.err"; then
    echo 'missing argument unexpectedly passed' >&2
    exit 1
else
    test $? -eq 2
fi

run_check env FIXTURE_TRAILER_LINES=100000 >"$work/current.out"
grep -Fxq 'status=up-to-date' "$work/current.out"
grep -Fxq 'renderer=wkhtmltox-1:0.12.6.1-3.bookworm' "$work/current.out"
grep -Fxq 'renderer_architecture=amd64' "$work/current.out"
grep -Fxq 'renderer_policy=pinned-manual-security-review' "$work/current.out"
run_check env FIXTURE_CANDIDATE=19.0.20260826 >"$work/newer.out"
grep -Fxq 'status=supervised-update-available' "$work/newer.out"

expect_failure missing-candidate env FIXTURE_CANDIDATE=
expect_failure no-candidate env FIXTURE_CANDIDATE='(none)'
expect_failure downgrade env FIXTURE_CANDIDATE=19.0.20260824
expect_failure wrong-key env FIXTURE_FINGERPRINT=0000000000000000000000000000000000000000
expect_failure wrong-install env FIXTURE_INSTALLED=19.0.20260824
expect_failure wrong-renderer env FIXTURE_RENDERER=1:0.12.6.1-2.bookworm
expect_failure wrong-renderer-architecture env FIXTURE_RENDERER_ARCHITECTURE=arm64

echo 'odoo updater fixture: PASS'
