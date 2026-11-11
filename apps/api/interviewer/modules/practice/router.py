"""Practice chat/session routes — mount PracticeChat without changing paths."""
from __future__ import annotations

from fastapi import FastAPI

from interviewer.chat_api import PracticeChat


def mount_practice(app: FastAPI, practice: PracticeChat) -> None:
    practice.mount(app)
