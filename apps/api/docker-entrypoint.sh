#!/bin/sh
# Compose/api image entrypoint: wait for Postgres, migrate (as MIGRATE_DATABASE_URL), then exec.
set -eu

psycopg_url() {
  printf '%s' "$1" | sed 's|postgresql+psycopg://|postgresql://|'
}

wait_postgres() {
  target_url="${1:-}"
  if [ -z "$target_url" ]; then
    return 0
  fi
  PG_WAIT_URL=$(psycopg_url "$target_url")
  export PG_WAIT_URL
  i=0
  until python -c "import os, psycopg; psycopg.connect(os.environ['PG_WAIT_URL']).close()"; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
      echo "postgres_connect_timeout" >&2
      exit 1
    fi
    sleep 1
  done
}

run_migrate() {
  migrate_url="${MIGRATE_DATABASE_URL:-${DATABASE_URL:-}}"
  if [ -z "$migrate_url" ]; then
    echo "DATABASE_URL or MIGRATE_DATABASE_URL required for migrate" >&2
    exit 1
  fi
  wait_postgres "$migrate_url"
  DATABASE_URL="$migrate_url" python -m interviewer.cli migrate
  # Ensure app role can use tables created by the migrate role (postgres).
  PG_WAIT_URL=$(psycopg_url "$migrate_url")
  export PG_WAIT_URL
  python -c "
import os, psycopg
with psycopg.connect(os.environ['PG_WAIT_URL']) as conn:
    conn.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aii_app')
    conn.execute('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO aii_app')
    conn.commit()
print('granted_aii_app_table_privileges')
"
}

mode="${1:-api}"
case "$mode" in
  api)
    run_migrate
    wait_postgres "${DATABASE_URL:-}"
    exec python -m uvicorn interviewer.main:app --host 0.0.0.0 --port 8000 --no-access-log
    ;;
  worker)
    wait_postgres "${DATABASE_URL:-}"
    exec python -m celery -A interviewer.workers.celery_app.celery_app worker --beat --loglevel=INFO -Q celery
    ;;
  migrate)
    run_migrate
    ;;
  *)
    exec "$@"
    ;;
esac
