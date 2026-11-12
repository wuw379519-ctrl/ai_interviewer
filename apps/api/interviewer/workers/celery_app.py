"""Celery application — broker/backend = REDIS_URL; eager mode for tests."""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "").lower() in {"1", "true", "yes"}

celery_app = Celery("ai_interviewer", include=[
    "interviewer.workers.tasks_report",
    "interviewer.workers.tasks_cleanup",
])
celery_app.conf.update(
    broker_url=REDIS_URL,
    result_backend=REDIS_URL,
    task_always_eager=ALWAYS_EAGER,
    task_eager_propagates=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Hourly retention sweep; dry_run=False only when CELERY_CLEANUP_EXECUTE=true.
    beat_schedule={
        "retention-cleanup-hourly": {
            "task": "interviewer.workers.tasks_cleanup.run_retention_cleanup",
            "schedule": crontab(minute=17),
            "kwargs": {
                "dry_run": os.environ.get("CELERY_CLEANUP_EXECUTE", "").lower()
                not in {"1", "true", "yes"},
            },
        },
    },
)
