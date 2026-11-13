#!/bin/sh
# Compose/api image entrypoint: wait for Postgres, migrate (api only), then exec.
set -eu

wait_postgres() {
  if [ -z "${DATABASE_URL:-}" ]; then
    return 0
  fi
  # psycopg accepts postgresql://; SQLAlchemy URL may use postgresql+psycopg://
  PG_WAIT_URL=$(printf '%s' "$DATABASE_URL" | sed 's|postgresql+psycopg://|postgresql://|')
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

mode="${1:-api}"
case "$mode" in
  api)
    wait_postgres
    python -m interviewer.cli migrate
    exec python -m uvicorn interviewer.main:app --host 0.0.0.0 --port 8000 --no-access-log
    ;;
  worker)
    wait_postgres
    exec python -m celery -A interviewer.workers.celery_app.celery_app worker --beat --loglevel=INFO -Q celery
    ;;
  migrate)
    wait_postgres
    exec python -m interviewer.cli migrate
    ;;
  *)
    exec "$@"
    ;;
esac
