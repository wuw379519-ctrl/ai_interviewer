"""Celery workers: async report generation and retention cleanup (Task 8a)."""
from __future__ import annotations

from .celery_app import celery_app

__all__ = ["celery_app"]
