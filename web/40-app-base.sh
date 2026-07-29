#!/bin/sh
# Stamp the app's mount point into index.html at container start.
#
# The nginx image runs every /docker-entrypoint.d/*.sh before starting nginx.
# APP_BASE is a path prefix with no trailing slash ("" for the root, "/lib"
# behind a shared reverse proxy). It has to be applied at RUNTIME: Vite inlines
# its `base` at build time, so baking the prefix in would tie the image to a
# single mount point.
#
# Always regenerated from index.html.template, so a restart cannot substitute
# twice or leave a stale prefix behind.
set -eu

BASE="${APP_BASE:-}"
# Tolerate a trailing slash in the env value; the template supplies its own.
case "$BASE" in
    */) BASE="${BASE%/}" ;;
esac

ROOT=/usr/share/nginx/html
TEMPLATE="$ROOT/index.html.template"

[ -f "$TEMPLATE" ] || { echo "40-app-base.sh: $TEMPLATE missing" >&2; exit 1; }

OUT="$ROOT/index.html"
sed "s|__APP_BASE__|${BASE}|g" "$TEMPLATE" > "$OUT"

# Verify the result instead of trusting it. A plain string replace is easy to
# aim at the wrong thing: the token once appeared inside a `window.__APP_BASE__`
# property name, so the substitution rewrote the identifier and the page shipped
# with `window./lib = "/lib"` — a syntax error that silently dropped the prefix
# from both the router and the API client. Fail the start instead.
if grep -q "__APP_BASE__" "$OUT"; then
    echo "40-app-base.sh: unsubstituted __APP_BASE__ left in index.html" >&2
    exit 1
fi
if [ "$(grep -c "<base href=\"${BASE}/\"" "$OUT")" != "1" ]; then
    echo "40-app-base.sh: expected exactly one <base href=\"${BASE}/\"> in index.html" >&2
    exit 1
fi
# The prefix belongs in an attribute value, never in code. Only meaningful when
# a prefix was actually substituted — with BASE empty the pattern would match
# any property access at all.
if [ -n "$BASE" ] && grep -qE "(window|document)\.${BASE#/}" "$OUT"; then
    echo "40-app-base.sh: prefix substituted into an identifier in index.html" >&2
    exit 1
fi

echo "40-app-base.sh: serving under '${BASE:-/}'"
