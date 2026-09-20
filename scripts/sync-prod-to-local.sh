#!/bin/sh
# Copy PRODUCTION data down to the local dev stack.
#
# The local database is a rehearsal surface: schema changes and tests run here,
# real corrections go to production (that rule is why this script only ever
# runs one way). It exists because a partial restore is worse than no restore —
# a local copy missing `jlc_order_decisions` showed 45 undecided JLC orders
# that production had decided months earlier, and looked like a regression in
# code that was fine.
#
#   scripts/sync-prod-to-local.sh              # database only
#   scripts/sync-prod-to-local.sh --files      # database + the MinIO objects
#   scripts/sync-prod-to-local.sh --lean       # skip the 2.5M-row flash logs
#   scripts/sync-prod-to-local.sh --check      # compare row counts, change nothing
#   scripts/sync-prod-to-local.sh --yes        # do not ask before wiping local
#
# It NEVER writes to production. Every prod command here is a read: `pg_dump`,
# `tar -c`, `psql -c select`. There is deliberately no flag that reverses the
# direction — pushing a developer's database over the real one is not a thing
# this repo should make easy.
#
# Wiping local is the whole point, so it asks first unless `--yes` is given.
set -eu

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"

SSH_HOST=${SSH_HOST:-ubuntu}
PROD_COMPOSE=${PROD_COMPOSE:-~/aws-deployment/docker-compose.kicadlib.yml}
# -p kicadlib is NOT optional: that directory holds several unrelated stacks and
# the project name is the only thing keeping them apart.
PROD="docker compose -p kicadlib -f $PROD_COMPOSE"
DB_USER=kicadlib
DB_NAME=kicadlib

WITH_FILES=0
LEAN=0
ASSUME_YES=0
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --files) WITH_FILES=1 ;;
    --lean) LEAN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --check) CHECK_ONLY=1 ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (try --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\n== %s\n' "$*"; }
prod_psql() { $PROD exec -T kicadlib-db psql -U "$DB_USER" -d "$DB_NAME" "$@"; }

# ---------------------------------------------------------------- row counts

# EXACT counts, not `pg_stat_user_tables.n_live_tup`. The estimate cannot tell
# a real gap from collector drift, and the first run of this script reported
# `run_cost_documents 86 vs 87` as "noise" when production had genuinely gained
# an invoice while the dump was being taken. A financial table being one row
# short is the thing this check exists to catch, so it must not be a guess.
# The cost is a sequential scan per table; `programming_logs` (2.5M rows) is
# the only one that is noticeable, and it is about a second.
COUNT_SQL="select string_agg(format('select %L t, count(*) n from %I.%I',
                                    tablename, schemaname, tablename),
                             ' union all ' order by tablename)
             from pg_tables where schemaname = 'public'"

# Two round trips: ask the catalogue for a query that counts every table, then
# run it. Writing the table list into the script would go stale on the next
# migration, which is exactly when this check matters most.
counts_local() {
  q=$(docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At -c "$COUNT_SQL")
  docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -At -F'|' -c "$q"
}
counts_prod() {
  q=$(ssh "$SSH_HOST" "$PROD exec -T kicadlib-db psql -U $DB_USER -d $DB_NAME -At -c \"$COUNT_SQL\"")
  ssh "$SSH_HOST" "$PROD exec -T kicadlib-db psql -U $DB_USER -d $DB_NAME -At -F'|' -c \"$q\""
}

compare_counts() {
  say "comparing row counts"
  counts_local >/tmp/kicadlib-local-counts.txt
  counts_prod >/tmp/kicadlib-prod-counts.txt
  python3 - <<'PY'
def read(p):
    out = {}
    for line in open(p):
        line = line.strip()
        if "|" in line:
            t, n = line.rsplit("|", 1)
            out[t] = int(n)
    return out

loc, pro = read("/tmp/kicadlib-local-counts.txt"), read("/tmp/kicadlib-prod-counts.txt")
missing, drifted = [], []
for t in sorted(set(loc) | set(pro)):
    a, b = loc.get(t), pro.get(t)
    if a == b:
        continue
    # A table that exists on one side only is a SCHEMA difference, which is
    # expected while a migration is undeployed — report it, do not alarm.
    if a is None or b is None:
        drifted.append((t, a, b, "table only on one side"))
    elif a == 0 and b > 0:
        missing.append((t, a, b))
    else:
        drifted.append((t, a, b, ""))

if missing:
    print("\nEMPTY LOCALLY, POPULATED ON PROD — a partial restore:")
    for t, a, b in missing:
        print(f"  {t:38} {a:>9} {b:>9}")
if drifted:
    # Exact counts, so every line here is a REAL difference. The usual cause is
    # that somebody kept using the platform while the dump was being taken, and
    # a live row is worth seeing rather than rounding away.
    print("\ndiffering (prod moved on, or something was written locally):")
    for t, a, b, why in drifted:
        print(f"  {t:38} {str(a):>9} {str(b):>9}  {why}")
if not missing and not drifted:
    print("  every table matches exactly")
elif not missing:
    print("\nno table is empty locally that is populated on prod")
PY
}

if [ "$CHECK_ONLY" = 1 ]; then
  compare_counts
  exit 0
fi

# ------------------------------------------------------------------ confirm

if [ "$ASSUME_YES" != 1 ]; then
  printf 'This DESTROYS the local database'
  [ "$WITH_FILES" = 1 ] && printf ' and the local MinIO objects'
  printf ' and replaces them with production.\nType yes to continue: '
  read -r reply
  [ "$reply" = "yes" ] || { echo "aborted"; exit 1; }
fi

docker compose up -d db minio >/dev/null
DUMP=$(mktemp -t kicadlib-prod-XXXXXX.dump)
trap 'rm -f "$DUMP"' EXIT

# ---------------------------------------------------------------- the dump

# Custom format (-Fc), because it restores in parallel and lets `pg_restore`
# drop objects in dependency order. --no-owner/--no-acl: the roles on the
# server are not the roles here, and a restore that tries to grant to a missing
# role stops halfway.
EXCLUDE=""
if [ "$LEAN" = 1 ]; then
  # `programming_logs` alone is ~2.5M rows and most of the 1.4 GB. Its SCHEMA
  # is still restored, so the flasher pages work — they are simply empty.
  EXCLUDE="--exclude-table-data=programming_logs --exclude-table-data=programming_steps"
  say "dumping production (lean — flash logs excluded)"
else
  say "dumping production (full, ~1.4 GB)"
fi

ssh "$SSH_HOST" "$PROD exec -T kicadlib-db pg_dump -U $DB_USER -d $DB_NAME \
  -Fc --no-owner --no-acl $EXCLUDE" > "$DUMP"
printf '   %s\n' "$(du -h "$DUMP" | cut -f1) written"

# --------------------------------------------------------------- the restore

# The api holds open connections, and `DROP SCHEMA` waits for every one of them.
say "stopping the api while the schema is replaced"
docker compose stop api >/dev/null 2>&1 || true

say "replacing the local schema"
docker compose exec -T db psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 -c \
  "select pg_terminate_backend(pid) from pg_stat_activity
     where datname = '$DB_NAME' and pid <> pg_backend_pid();" >/dev/null
docker compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
  -c "drop schema public cascade;" -c "create schema public;" >/dev/null

say "restoring"
# The dump goes INTO the container first. `pg_restore --jobs` refuses a dump on
# standard input ("parallel restore from standard input is not supported"), and
# a 1.4 GB serial restore is several minutes of waiting for nothing.
docker compose cp "$DUMP" db:/tmp/prod.dump
# pg_restore reports non-fatal notices on extensions and comments it cannot
# recreate as a non-zero exit; --exit-on-error is off on purpose, and the row
# comparison at the end is what actually proves the restore landed.
docker compose exec -T db pg_restore -U "$DB_USER" -d "$DB_NAME" \
  --no-owner --no-acl --jobs 4 /tmp/prod.dump 2>&1 | grep -v "^$" | tail -5 || true
docker compose exec -T db rm -f /tmp/prod.dump

# ------------------------------------------------------------------- files

if [ "$WITH_FILES" = 1 ]; then
  say "copying MinIO objects (~570 MB)"
  # Tar runs on the SERVER, not in `kicadlib-minio` — that image ships no tar.
  # It does not need to: MinIO's data on the server is a host BIND mount, so
  # the files are ordinary files. Ask docker where, rather than hard-coding a
  # path that moves the next time the stack is rearranged.
  SRC=$(ssh "$SSH_HOST" "docker inspect kicadlib-minio \
        --format '{{range .Mounts}}{{if eq .Destination \"/data\"}}{{.Source}}{{end}}{{end}}'")
  [ -n "$SRC" ] || { echo "cannot find the prod MinIO data directory" >&2; exit 1; }
  # Locally it is a named volume, reached through a throwaway container so
  # nothing holds the files open while they are replaced.
  docker compose stop minio >/dev/null 2>&1 || true
  VOL=$(docker volume ls -q | grep -E 'kicadlib-platform_miniodata$' | head -1)
  [ -n "$VOL" ] || { echo "no local miniodata volume found" >&2; exit 1; }
  ssh "$SSH_HOST" "tar -C '$SRC' -cf - ." \
    | docker run --rm -i -v "$VOL":/data alpine sh -c \
        'find /data -mindepth 1 -delete 2>/dev/null; tar -C /data -xf -'
  docker compose up -d minio >/dev/null
fi

# ------------------------------------------------------------------- finish

say "starting the api (its startup DDL runs against the restored schema)"
docker compose up -d api >/dev/null
# The api answers /api/health/schema only once the phase-1 statements have run.
i=0
while [ $i -lt 40 ]; do
  if curl -sf -o /dev/null http://127.0.0.1:8020/openapi.json; then break; fi
  i=$((i + 1))
  sleep 2
done

compare_counts

say "done"
echo "   Check the startup migrations: GET /api/health/schema"
echo "   Nothing was written to production."
