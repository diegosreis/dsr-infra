#!/bin/sh
# All nginx stderr (including startup, internal redirects and other vhosts)
# must pass this filter BEFORE Docker/supervisor receives it. No raw fallback.
set -eu
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -r "$base/redactor.awk" ] || { echo 'nginx log redactor missing' >&2; exit 78; }
# Verify the filter before starting nginx; missing/broken awk must fail closed.
if ! awk -f "$base/redactor.awk" </dev/null >/dev/null 2>&1; then
    echo 'nginx log redactor unavailable' >&2
    exit 78
fi
work=$(mktemp -d "${TMPDIR:-/tmp}/gd-nginx-stderr.XXXXXX")
mkfifo "$work/stderr"
child= filter=
cleanup() { rm -rf "$work"; }
forward() { [ -z "$child" ] || kill -s "$1" "$child" 2>/dev/null || :; }
trap cleanup EXIT
trap 'forward TERM' TERM
trap 'forward QUIT' QUIT
trap 'forward INT' INT
trap 'forward HUP' HUP
awk -f "$base/redactor.awk" < "$work/stderr" >&2 &
filter=$!
"$@" 2> "$work/stderr" &
child=$!
# wait may be interrupted by a forwarded signal; keep waiting for the child.
rc=0
while :; do
    set +e
    wait "$child"
    rc=$?
    set -e
    kill -0 "$child" 2>/dev/null || break
done
set +e
wait "$filter"
filter_rc=$?
set -e
[ "$filter_rc" -eq 0 ] || exit 74
exit "$rc"
