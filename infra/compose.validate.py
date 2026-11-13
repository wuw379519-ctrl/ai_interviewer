"""Offline compose structural gate (Task 8a) — does NOT replace docker compose up."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPOSE = ROOT / "docker-compose.yml"
INIT_SQL = ROOT / "postgres" / "init-app-role.sql"
NGINX = ROOT / "nginx" / "nginx.conf"
ENTRYPOINT = ROOT.parent / "apps" / "api" / "docker-entrypoint.sh"


def main() -> int:
    text = COMPOSE.read_text(encoding="utf-8")
    errors: list[str] = []

    for token in (
        "postgres:", "redis:", "api:", "worker:",
        "/api/ready", "REDIS_URL", "DATABASE_URL", "LLM_PROVIDER",
        "FEISHU_APP_ID", "worker",
    ):
        if token not in text:
            errors.append(f"missing token {token!r}")

    if not ENTRYPOINT.is_file():
        errors.append("apps/api/docker-entrypoint.sh missing")
    else:
        entry = ENTRYPOINT.read_text(encoding="utf-8")
        for token in (
            "celery",
            "--beat",
            "interviewer.cli migrate",
            "wait_postgres",
            "MIGRATE_DATABASE_URL",
            "aii_app",
        ):
            if token not in entry:
                errors.append(f"entrypoint missing token {token!r}")
        if "aii_app:aii_app_dev_only" not in text:
            errors.append("api/worker DATABASE_URL must use aii_app (NOBYPASSRLS) for /api/ready")
        if "MIGRATE_DATABASE_URL" not in text:
            errors.append("MIGRATE_DATABASE_URL missing for superuser migrate")
        if "command: [\"api\"]" not in text and "command: ['api']" not in text:
            # Accept either quoting style for the api service command.
            if not re.search(r"command:\s*\[\s*[\"']api[\"']\s*\]", text):
                errors.append("api command must be entrypoint mode ['api']")
        if not re.search(r"command:\s*\[\s*[\"']worker[\"']\s*\]", text):
            errors.append("worker command must be entrypoint mode ['worker']")

    # depends_on order: api waits for postgres+redis healthy; worker waits for api healthy.
    if not re.search(r"api:[\s\S]*?depends_on:[\s\S]*?postgres:[\s\S]*?condition:\s*service_healthy", text):
        errors.append("api missing depends_on postgres healthy")
    if not re.search(r"api:[\s\S]*?depends_on:[\s\S]*?redis:[\s\S]*?condition:\s*service_healthy", text):
        errors.append("api missing depends_on redis healthy")
    if not re.search(r"worker:[\s\S]*?depends_on:[\s\S]*?api:[\s\S]*?condition:\s*service_healthy", text):
        errors.append("worker missing depends_on api healthy")

    # healthcheck must hit /api/ready (not /api/health).
    if "/api/health" in text and re.search(r"healthcheck:[\s\S]{0,400}/api/health", text):
        errors.append("healthcheck must not use /api/health")
    if not re.search(r"healthcheck:[\s\S]{0,500}/api/ready", text):
        errors.append("api healthcheck must reference /api/ready")

    # env_file optional path documented; no real secrets in compose.
    if "sk-" in text or "SECRET_KEY=" in text:
        errors.append("compose must not embed real-looking secrets")
    if "../.env" not in text:
        errors.append("env_file ../.env reference missing")

    # volume mount for init role script.
    if "./postgres/init-app-role.sql:/docker-entrypoint-initdb.d/01-app-role.sql" not in text:
        errors.append("init-app-role.sql volume mount / order (01-) missing")
    if "aii_pg_data" not in text:
        errors.append("postgres named volume aii_pg_data missing")

    role = INIT_SQL.read_text(encoding="utf-8")
    if "NOSUPERUSER" not in role or "NOBYPASSRLS" not in role:
        errors.append("init-app-role.sql missing NOSUPERUSER NOBYPASSRLS")

    nginx = NGINX.read_text(encoding="utf-8")
    if "ip_hash" not in nginx:
        errors.append("nginx sticky ip_hash missing")

    if errors:
        print("compose_validate_failed:", file=sys.stderr)
        for item in errors:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print("compose_ok")
    print("covered: service names, depends_on healthy chain, /api/ready healthcheck string,")
    print("  env_file path, init-app-role mount order 01-, NOSUPERUSER NOBYPASSRLS,")
    print("  worker --beat, nginx ip_hash, no obvious secrets in compose YAML")
    print("NOT covered (need docker compose up / CI): image pull, healthcheck process exit,")
    print("  migrate+ready against live PG, redis ping, celery broker connect, beat tick,")
    print("  volume create, initdb script execution order at runtime, resource limits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
