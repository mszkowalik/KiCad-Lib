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

sed "s|__APP_BASE__|${BASE}|g" "$TEMPLATE" > "$ROOT/index.html"

echo "40-app-base.sh: serving under '${BASE:-/}'"
