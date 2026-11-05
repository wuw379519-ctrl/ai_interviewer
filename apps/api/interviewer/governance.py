from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Table, and_, func, or_, select

from .repository import StorageSession

from . import database as db
from .auth import Actor, b64, unb64
from .contracts import CleanupInput, Object, RetentionInput
from .errors import DomainError
from .safety import json_hash, sanitize_metadata
from .service import Result, object_value, strings

if TYPE_CHECKING:
    from .service import Service

ERASED: Object = {"error": {"code": "CANDIDATE_DELETED", "message": "关联资料已按删除或保留期策略清除", "details": None}}


def minimized(action: str, value: object) -> Object:
    metadata = object_value(value or {})
    result: Object = {"erased": True}
    if action == "score.revised":
        for key in ["oldValue", "newValue"]:
            if metadata.get(key) in {"1", "2", "3", "4", "5", "insufficient_evidence"}:
                result[key] = metadata[key]
    return result


def preview_erasure(service: Service, connection: StorageSession, candidate_id: str) -> Object:
    person = service.required(connection, db.candidates, candidate_id, "CANDIDATE_NOT_FOUND")
    owned = select(db.interviews.c.id).where(db.interviews.c.candidate_id == candidate_id)

    def count(entity: Table, condition: object) -> int:
        return int(str(db.scalar(connection, select(func.count()).select_from(entity).where(condition))))  # type: ignore[arg-type]
    return {"candidateId": candidate_id, "label": f"候选人 {candidate_id[:8]}", "deleted": bool(person.get("erased_at")),
            "counts": {"interviews": count(db.interviews, db.interviews.c.candidate_id == candidate_id),
                       "resumes": count(db.resumes, db.resumes.c.candidate_id == candidate_id),
                       "turns": count(db.turns, db.turns.c.interview_id.in_(owned)),
                       "reports": count(db.reports, db.reports.c.interview_id.in_(owned)),
                       "scores": count(db.scores, db.scores.c.interview_id.in_(owned)),
                       "caches": count(db.idempotency_keys, db.idempotency_keys.c.owner_candidate_id == candidate_id)}}


def erase_interviews(service: Service, connection: StorageSession, identities: list[str]) -> int:
    if not identities:
        return 0
    found = db.rows(connection, select(db.interviews).where(db.interviews.c.id.in_(identities)))
    identities = [str(row["id"]) for row in found]
    for row in db.rows(connection, select(db.audit_logs).where(db.audit_logs.c.interview_id.in_(identities))):
        db.update(connection, db.audit_logs, str(row["id"]), metadata=minimized(str(row["action"]), row["metadata"]), ip_hash=None)
    db.command(connection, db.idempotency_keys.update().where(db.idempotency_keys.c.owner_interview_id.in_(identities)).values(response_status=410, response_body=ERASED, status='completed', updated_at=db.now()))
    db.command(connection, db.scores.delete().where(db.scores.c.interview_id.in_(identities)))
    db.command(connection, db.evidence.delete().where(db.evidence.c.interview_id.in_(identities)))
    db.command(connection, db.interviews.delete().where(db.interviews.c.id.in_(identities)))
    service.speech_cache = {key: value for key, value in service.speech_cache.items() if value[3] not in identities}
    return len(found)


def erase_candidate(service: Service, connection: StorageSession, candidate_id: str, reason: str, actor: Actor) -> Result:
    person = service.required(connection, db.candidates, candidate_id, "CANDIDATE_NOT_FOUND")
    if person.get("erased_at"):
        return Result({"candidateId": candidate_id, "deleted": True, "alreadyDeleted": True, "interviewsErased": 0})
    owned = db.rows(connection, select(db.interviews).where(db.interviews.c.candidate_id == candidate_id))
    count = erase_interviews(service, connection, [str(row["id"]) for row in owned])
    db.command(connection, db.resumes.delete().where(db.resumes.c.candidate_id == candidate_id))
    db.command(connection, db.idempotency_keys.update().where(db.idempotency_keys.c.owner_candidate_id == candidate_id).values(response_status=410, response_body=ERASED, status='completed', updated_at=db.now()))
    for row in db.rows(connection, select(db.audit_logs).where(or_(db.audit_logs.c.entity_id == candidate_id, db.audit_logs.c.actor_id == candidate_id))):
        db.update(connection, db.audit_logs, str(row["id"]), metadata=minimized(str(row["action"]), row["metadata"]), ip_hash=None)
    db.update(connection, db.candidates, candidate_id, full_name="已删除候选人", email=None, phone=None, source=None,
              deleted_at=person.get("deleted_at") or db.now(), erased_at=db.now())
    service.audit(connection, "candidate.erased", candidate_id,
                  {"reasonKind": "candidate_request", "reasonDigest": hashlib.sha256(reason.encode()).hexdigest(), "interviewsErased": count}, actor)
    return Result({"candidateId": candidate_id, "deleted": True, "alreadyDeleted": False, "interviewsErased": count})


def update_policy(service: Service, connection: StorageSession, body: RetentionInput, actor: Actor) -> Result:
    policy = service.policy(connection)
    if policy["revision"] != body.expected_revision:
        raise DomainError("RESOURCE_CONFLICT", "策略已更新，请刷新")
    db.update(connection, db.data_policies, "workspace", retention_days=body.retention_days,
              revision=body.expected_revision + 1, updated_by=actor.id)
    service.audit(connection, "retention.policy_updated", "workspace", {"old": policy, "current": service.policy(connection), "reason": body.reason}, actor)
    return Result(service.policy(connection))


def cleanup_selection(service: Service, connection: StorageSession, cutoff: object | None = None) -> tuple[Object, bool]:
    at = db.utc(cutoff) if cutoff is not None else db.now()
    if at > db.now():
        raise DomainError("VALIDATION_FAILED", "清理截止时间不能在未来")
    selected: dict[str, list[str]] = {}
    has_more = False
    conditions = [
        ("candidateIds", db.candidates, and_(db.candidates.c.erased_at.is_(None), or_(db.candidates.c.retained_until <= at, db.candidates.c.deleted_at.is_not(None))), 25),
        ("interviewIds", db.interviews, db.interviews.c.retained_until <= at, 25),
        ("cacheIds", db.idempotency_keys, db.idempotency_keys.c.expires_at <= at, 200),
        ("auditIds", db.audit_logs, db.audit_logs.c.created_at <= at - timedelta(days=90), 100),
    ]
    for key, entity, condition, limit in conditions:
        statement = select(entity.c.id).where(condition)
        if key == "interviewIds":
            statement = statement.where(db.interviews.c.candidate_id.not_in(selected["candidateIds"]))
        if key == "auditIds":
            # SQL-side bounded exclusion; no transcript is needed to select expired contexts.
            statement = statement.where(entity.c.metadata.is_not(None))
        found = [str(row["id"]) for row in db.rows(connection, statement.order_by(entity.c.id).limit(limit + 1))]
        selected[key] = found[:limit]
        has_more |= len(found) > limit
    return {"cutoffAt": db.iso(at), "policyRevision": service.policy(connection)["revision"], **selected}, has_more


def cleanup_preview(service: Service, connection: StorageSession) -> Object:
    selection, more = cleanup_selection(service, connection)
    fingerprint = json_hash(selection)
    payload = b64(json.dumps({"cutoff": selection["cutoffAt"], "fingerprint": fingerprint,
                              "expires": int(time.time()) + 300}, separators=(",", ":")).encode())
    token = payload + "." + service.auth.digest("retention-preview:" + payload)
    return {**selection, "fingerprint": fingerprint, "previewToken": token, "hasMore": more,
            "counts": {"candidates": len(strings(selection["candidateIds"])), "interviews": len(strings(selection["interviewIds"])),
                       "caches": len(strings(selection["cacheIds"])), "auditEntries": len(strings(selection["auditIds"]))}}


def run_cleanup(service: Service, connection: StorageSession, body: CleanupInput, actor: Actor) -> Result:
    try:
        payload, signature = body.preview_token.split(".")
        if not hmac.compare_digest(signature, service.auth.digest("retention-preview:" + payload)):
            raise ValueError("signature")
        data = object_value(json.loads(unb64(payload)))
        if int(str(data["expires"])) <= int(time.time()):
            raise DomainError("RESOURCE_CONFLICT", "清理预览已过期，请重新预览")
    except (ValueError, KeyError) as error:
        raise DomainError("VALIDATION_FAILED", "清理预览凭证无效") from error
    selection, _ = cleanup_selection(service, connection, data["cutoff"])
    if data["fingerprint"] != json_hash(selection):
        raise DomainError("RESOURCE_CONFLICT", "资料或策略已变化，请重新预览")
    candidates = strings(selection["candidateIds"])
    for identity in candidates:
        erase_candidate(service, connection, identity, body.reason, actor)
    interviews = erase_interviews(service, connection, strings(selection["interviewIds"]))
    cache_ids, audit_ids = strings(selection["cacheIds"]), strings(selection["auditIds"])
    db.command(connection, db.idempotency_keys.delete().where(db.idempotency_keys.c.id.in_(cache_ids)))
    for identity in audit_ids:
        row = db.one(connection, db.audit_logs, identity)
        if row:
            db.update(connection, db.audit_logs, identity, metadata=None, ip_hash=None)
    result: Object = {"candidatesErased": len(candidates), "interviewsErased": interviews, "cachesRemoved": len(cache_ids), "auditEntriesMinimized": len(audit_ids)}
    service.audit(connection, "retention.executed", "workspace", {**result, "reasonDigest": hashlib.sha256(body.reason.encode()).hexdigest()}, actor)
    return Result(result)


def candidates_page(service: Service, connection: StorageSession, before: str | None) -> Object:
    statement = select(db.candidates, db.jobs.c.title).join(db.jobs, db.jobs.c.id == db.candidates.c.job_id)
    if before:
        cursor = service.required(connection, db.candidates, before, "VALIDATION_FAILED")
        statement = statement.where(or_(db.candidates.c.created_at < cursor["created_at"], and_(db.candidates.c.created_at == cursor["created_at"], db.candidates.c.id < before)))
    found = db.rows(connection, statement.order_by(db.candidates.c.created_at.desc(), db.candidates.c.id.desc()).limit(26))
    return {"items": [{"id": str(row["id"]), "label": f"候选人 {str(row['id'])[:8]}", "jobTitle": str(row["title"]),
                        "deleted": bool(row["erased_at"]), "retainedUntil": db.iso(row["retained_until"])} for row in found[:25]],
            "nextCursor": str(found[24]["id"]) if len(found) > 25 else None}


def audit_page(service: Service, connection: StorageSession, actor: Actor, before: str | None,
               action: str | None, interview_id: str | None, limit: int) -> Object:
    statement = select(db.audit_logs)
    if before:
        cursor = service.required(connection, db.audit_logs, before, "VALIDATION_FAILED")
        statement = statement.where(or_(db.audit_logs.c.created_at < cursor["created_at"], and_(db.audit_logs.c.created_at == cursor["created_at"], db.audit_logs.c.id < before)))
    if action:
        statement = statement.where(db.audit_logs.c.action == action)
    if interview_id:
        statement = statement.where(db.audit_logs.c.interview_id == interview_id)
    found = db.rows(connection, statement.order_by(db.audit_logs.c.created_at.desc(), db.audit_logs.c.id.desc()).limit(limit + 1))
    items: list[Object] = []
    for row in found[:limit]:
        meta = minimized(str(row["action"]), row["metadata"]) if db.utc(row["created_at"]) <= db.now() - timedelta(days=90) else sanitize_metadata(row["metadata"] or {})
        items.append({"id": str(row["id"]), "action": str(row["action"]), "actorType": str(row["actor_type"]),
                      "actorId": str(row["actor_id"]) if row["actor_id"] else None, "entityId": str(row["entity_id"]) if row["entity_id"] else None,
                      "interviewId": str(row["interview_id"]) if row["interview_id"] else None, "at": db.iso(row["created_at"]), "metadata": meta})
    service.audit(connection, "audit.viewed", "workspace", {"limit": limit}, actor)
    return {"items": items, "nextCursor": str(found[limit - 1]["id"]) if len(found) > limit else None}
