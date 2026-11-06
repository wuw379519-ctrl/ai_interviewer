from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.sql import Select

from . import assessment, database as db
from .auth import Actor
from .contracts import Object, ReportDocument
from .errors import DomainError
from .repository import StorageSession
from .safety import redact
from .service import Service, as_int

PAGE_SIZE = 25


def retained_records() -> Select[tuple[object, ...]]:
    now = db.now()
    return (
        select(db.interviews.c.id, db.interviews.c.created_at, db.interviews.c.started_at,
               db.interviews.c.finished_at, db.interviews.c.retained_until, db.interviews.c.status,
               db.interviews.c.mode, db.jobs.c.title, db.candidates.c.full_name)
        .join(db.jobs, db.jobs.c.id == db.interviews.c.job_id)
        .join(db.candidates, db.candidates.c.id == db.interviews.c.candidate_id)
        .where(db.interviews.c.retained_until > now, db.candidates.c.retained_until > now,
               db.candidates.c.deleted_at.is_(None))
    )


def summary(row: db.Row) -> Object:
    return {"id": str(row["id"]), "jobTitle": redact(str(row["title"])),
            "candidateName": redact(str(row["full_name"])), "status": str(row["status"]),
            "mode": str(row["mode"]), "createdAt": db.iso(row["created_at"]),
            "startedAt": db.iso(row["started_at"]) if row["started_at"] else None,
            "finishedAt": db.iso(row["finished_at"]) if row["finished_at"] else None,
            "retainedUntil": db.iso(row["retained_until"])}


def page(service: Service, connection: StorageSession, before: str | None) -> Object:
    statement = retained_records()
    if before:
        cursor = service.required(connection, db.interviews, before, "VALIDATION_FAILED")
        statement = statement.where(or_(db.interviews.c.created_at < cursor["created_at"],
                                        and_(db.interviews.c.created_at == cursor["created_at"], db.interviews.c.id < before)))
    rows = db.rows(connection, statement.order_by(db.interviews.c.created_at.desc(), db.interviews.c.id.desc()).limit(PAGE_SIZE + 1))
    return {"items": [summary(row) for row in rows[:PAGE_SIZE]],
            "nextCursor": str(rows[PAGE_SIZE - 1]["id"]) if len(rows) > PAGE_SIZE else None}


def detail(service: Service, connection: StorageSession, identity: str, actor: Actor) -> Object:
    rows = db.rows(connection, retained_records().where(db.interviews.c.id == identity))
    if not rows:
        raise DomainError("INTERVIEW_NOT_FOUND", "面试记录不存在或已到期")
    row = rows[0]
    consented = row["status"] != "cancelled" and db.exists(
        connection, select(db.consents.c.id).where(db.consents.c.interview_id == identity,
                                                   db.consents.c.revoked_at.is_(None),
                                                   db.consents.c.consent_version != "",
                                                   db.consents.c.consent_text_hash != ""))
    turns = service.turn_rows(connection, identity) if consented else []
    report = (ReportDocument.model_validate(assessment.report_document(service, connection, identity)).payload()
              if consented and row["status"] in {"report_ready", "reviewed"} else None)
    service.audit(connection, "interview.record_viewed", identity, actor=actor, interview_id=identity)
    return {"interview": summary(row), "report": report,
            "turns": [{"seq": as_int(turn, "seq"), "role": str(turn["role"]),
                       "content": redact(str(turn["content"]), str(row["full_name"]))} for turn in turns]}
