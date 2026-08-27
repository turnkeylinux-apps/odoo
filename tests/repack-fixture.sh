#!/bin/bash
set -Eeuo pipefail
umask 077

repo=$(cd "$(dirname "$0")/.." && pwd)
repack=$repo/overlay/usr/local/sbin/odoo-repack-package
updater=$repo/overlay/usr/local/sbin/odoo-update
work=$(mktemp -d /tmp/odoo-repack-fixture.XXXXXXXX)
trap 'find "$work" -depth -delete' EXIT

make_package() {
    local name=$1
    local dependency=$2
    local output=$3
    local root=$work/root-$name-$(basename "$output")
    mkdir -p "$root/DEBIAN" "$root/usr/share/odoo"
    chmod 0755 "$root" "$root/DEBIAN" "$root/usr" \
        "$root/usr/share" "$root/usr/share/odoo"
    printf '%s\n' \
        "Package: $name" \
        'Version: 19.0.20990101' \
        'Architecture: all' \
        'Maintainer: Odoo S.A. <info@odoo.com>' \
        "Depends: bash, $dependency" \
        'Description: Odoo repack fixture' >"$root/DEBIAN/control"
    printf '%s\n' '#!/bin/sh' 'exit 0' >"$root/DEBIAN/postinst"
    chmod 0755 "$root/DEBIAN/postinst"
    printf '%s\n' 'official-upstream-payload' >"$root/usr/share/odoo/payload"
    dpkg-deb --build --root-owner-group -Zxz "$root" "$output" >/dev/null
}

expect_repack_failure() {
    local input=$1
    local output=$2
    if "$repack" "$input" "$output" >"$work/unexpected-output" 2>"$work/expected-error"; then
        echo "fixture unexpectedly repacked $input" >&2
        exit 1
    fi
    test ! -e "$output"
}

original=$work/odoo-original.deb
repacked_one=$work/odoo-repacked-one.deb
repacked_two=$work/odoo-repacked-two.deb
make_package odoo python3-pypdf2 "$original"
"$repack" "$original" "$repacked_one" >"$work/metadata-one"
"$repack" "$original" "$repacked_two" >"$work/metadata-two"
test "$(sha256sum "$repacked_one" | awk '{ print $1 }')" = \
    "$(sha256sum "$repacked_two" | awk '{ print $1 }')"
dpkg-deb -f "$repacked_one" Depends |
    grep -Fxq 'bash, python3-pypdf2 | python3-pypdf'
original_fields=$(dpkg-deb -f "$original")
repacked_fields=$(dpkg-deb -f "$repacked_one")
test "${repacked_fields/python3-pypdf2 | python3-pypdf/python3-pypdf2}" = \
    "$original_fields"
mkdir "$work/original-control" "$work/repacked-control"
dpkg-deb --control "$original" "$work/original-control"
dpkg-deb --control "$repacked_one" "$work/repacked-control"
test "$(sha256sum "$work/original-control/postinst" | awk '{ print $1 }')" = \
    "$(sha256sum "$work/repacked-control/postinst" | awk '{ print $1 }')"
test "$(dpkg-deb --fsys-tarfile "$original" | sha256sum | awk '{ print $1 }')" = \
    "$(dpkg-deb --fsys-tarfile "$repacked_one" | sha256sum | awk '{ print $1 }')"
grep -Fxq 'dependency_rewrite=python3-pypdf2_to_python3-pypdf2_or_python3-pypdf' \
    "$work/metadata-one"

already_fixed=$work/odoo-already-fixed.deb
missing_dependency=$work/odoo-missing-dependency.deb
wrong_package=$work/not-odoo.deb
make_package odoo 'python3-pypdf2 | python3-pypdf' "$already_fixed"
make_package odoo python3-requests "$missing_dependency"
make_package other python3-pypdf2 "$wrong_package"
expect_repack_failure "$already_fixed" "$work/already-fixed-output.deb"
expect_repack_failure "$missing_dependency" "$work/missing-output.deb"
expect_repack_failure "$wrong_package" "$work/wrong-package-output.deb"

# Exercise the updater's signed-download boundary with a deterministic fixture.
# shellcheck disable=SC1090
. "$updater"
repack_command=$repack
candidate=19.0.20990101
fixture_download=$original
download_candidate() {
    cp "$fixture_download" "$1/odoo_${candidate}_all.deb"
}
signed_candidate_sha256() {
    sha256sum "$fixture_download" | awk '{ print $1 }'
}
prepare_candidate "$work/updater-prepared.deb" >"$work/updater-result"
dpkg-deb -f "$work/updater-prepared.deb" Depends |
    grep -Fxq 'bash, python3-pypdf2 | python3-pypdf'
grep -Fxq "candidate=$candidate" "$work/updater-result"

signed_candidate_sha256() {
    printf '%064d\n' 0
}
if prepare_candidate "$work/updater-rejected.deb" >"$work/rejected-result" 2>"$work/rejected-error"; then
    echo 'updater accepted a package that did not match signed metadata' >&2
    exit 1
fi
test ! -e "$work/updater-rejected.deb"

approved_sha=$(sha256sum "$repacked_one" | awk '{ print $1 }')
prepare_candidate() {
    cp "$repacked_one" "$1"
    printf '%s\n' \
        "candidate=$candidate" \
        "upstream_package_sha256=$(sha256sum "$original" | awk '{ print $1 }')" \
        "repacked_package_sha256=$approved_sha" \
        'upstream_payload_sha256=fixture-payload-sha256' \
        'dependency_rewrite=python3-pypdf2_to_python3-pypdf2_or_python3-pypdf' \
        "prepared=$1"
}
install_package() {
    test -f "$1"
    applied_package=1
}
installed_version_after_install() {
    printf '%s\n' "$candidate"
}
record_installation() {
    recorded_installation="$*"
}
applied_package=
recorded_installation=
apply_candidate "$approved_sha" >"$work/apply-result"
test "$applied_package" = 1
test -n "$recorded_installation"
grep -Fxq "installed=$candidate" "$work/apply-result"

applied_package=
if apply_candidate "$(printf '%064d' 0)" >"$work/apply-rejected" 2>"$work/apply-error"; then
    echo 'updater applied a package without the approved repacked hash' >&2
    exit 1
fi
test -z "$applied_package"

printf '%s\n' 'odoo-repack-fixture=PASS'
