from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast

from sqlalchemy import and_, select

from .repository import StorageSession

from . import database as db, events
from .auth import Actor
from .contracts import AssessmentSample, GraduateInput, Object, RevisionInput, ReviewInput, ScoreValue
from .domain import FORMAL_CAMPUS_PLAN, FORMAL_CAMPUS_TOPICS, GRADUATE_POLICY, TOPICS, eligibility, fixture_assessment, scoring_prompt
from .errors import DomainError
from .safety import INJECTION, assessment_text, guard_output, json_hash, redact
from .service import Result, as_int, object_value, objects

if TYPE_CHECKING:
    from .service import Service


def campus_summary(service: Service, connection: StorageSession, interview: db.Row) -> Object | None:
    if interview["recruitment_track"] != "graduate_campus":
        return None
    questions = service.question_rows(connection, str(interview["id"]))
    turns = service.turn_rows(connection, str(interview["id"]))
    person = service.candidate(connection, str(interview["candidate_id"]))
    topics: list[Object] = []
    for topic in FORMAL_CAMPUS_TOPICS if interview["plan_version"] == FORMAL_CAMPUS_PLAN else TOPICS:
        question = next((row for row in questions if row["topic_key"] == topic["key"]), None)
        matching = [row for row in turns if question and row["question_id"] == question["id"]]
        topics.append({"key": topic["key"], "label": topic["label"], "sourceNumber": topic["sourceNumber"],
                       "asked": any(row["role"] == "interviewer" for row in matching),
                       "answered": any(row["role"] == "candidate" for row in matching),
                       "skipped": bool(question and question["status"] == "skipped"),
                       "responses": [{"turnId": str(row["id"]), "quote": redact(str(row["content"]), str(person["full_name"]))[:4000]}
                                     for row in matching if row["role"] == "candidate"]})
    verification = object_value(interview["graduate_verification"]) if interview.get("graduate_verification") else None
    return {"policyVersion": GRADUATE_POLICY, "cet4Minimum": 425, **eligibility(verification), "verification": verification,
            "mandatoryAsked": sum(bool(row["asked"]) for row in topics), "mandatoryAnswered": sum(bool(row["answered"]) for row in topics),
            "mandatoryTotal": len(topics), "topics": topics}


def report_document(service: Service, connection: StorageSession, interview_id: str, audit: bool = False,
                    actor: Actor | None = None) -> Object:
    interview = service.interview(connection, interview_id, True)
    report_rows = db.rows(connection, select(db.reports).where(db.reports.c.interview_id == interview_id))
    if not report_rows:
        raise DomainError("INTERVIEW_NOT_FOUND", "面试报告尚未生成")
    report = report_rows[0]
    person = service.candidate(connection, str(interview["candidate_id"]))
    dimensions = service.dimensions(connection, str(interview["job_id"]))
    score_rows = db.rows(connection, select(db.scores).where(and_(db.scores.c.interview_id == interview_id, db.scores.c.attempt == 1)))
    evidence_rows = db.rows(connection, select(db.evidence).where(db.evidence.c.interview_id == interview_id))
    turns = service.turn_rows(connection, interview_id)
    questions = objects(report["question_scores"])
    result_dimensions: list[Object] = []
    for dimension in dimensions:
        score = next((row for row in score_rows if row["competency_id"] == dimension["id"]), None)
        value = str(score["value"]) if score else "insufficient_evidence"
        previous = next((row for row in objects(report["dimension_scores"]) if row.get("competencyId") == dimension["id"]), {})
        result_dimensions.append({"competencyId": dimension["id"], "competencyName": dimension["name"], "weight": dimension["weight"],
                                  "score": value, "scoreId": str(score["id"]) if score else "", "rationale": str(score["rationale"] or "") if score else "证据不足",
                                  "needsReview": bool(score and score["needs_review"]), "sampleValues": previous.get("sampleValues", []),
                                  "evidenceIds": [str(row["id"]) for row in evidence_rows if row["competency_id"] == dimension["id"]] if value != "insufficient_evidence" else []})
    coverage = sum(float(str(row["weight"])) for row in result_dimensions if row["score"] != "insufficient_evidence")
    complete = all(row["score"] != "insufficient_evidence" for row in result_dimensions)
    overall = round(sum(float(str(row["weight"])) * int(str(row["score"])) for row in result_dimensions), 2) if complete else None
    recommendation = "mixed" if overall is None else "strong_yes" if overall >= 4.25 else "yes" if overall >= 3.5 else "mixed" if overall >= 2.5 else "no"
    reason = "按已确认岗位权重与原文行为聚合，仅供人类复核，不自动决定录用或淘汰。"
    campus = campus_summary(service, connection, interview)
    if campus and campus["status"] == "not_met" and interview["plan_version"] == FORMAL_CAMPUS_PLAN:
        recommendation = "no"
        reason = "人工核验确认未满足岗位硬性资格。能力评分单独保留，由招聘者决定后续处理。"
    elif campus and (campus["status"] != "met" or campus["mandatoryAsked"] != campus["mandatoryTotal"]):
        recommendation = "mixed"
        reason = "岗位硬指标尚待核验、不满足，或固定必问尚未全部触达；能力分不能抵消硬指标，请招聘者人工处理。"
    revisions = db.rows(connection, select(db.score_revisions).where(db.score_revisions.c.score_id.in_([str(row["id"]) for row in score_rows])).order_by(db.score_revisions.c.created_at))
    if audit:
        service.audit(connection, "report.viewed", interview_id, actor=actor, interview_id=interview_id)
    summary = f"本次{sum(row['score'] != 'insufficient_evidence' for row in result_dimensions)}/{len(dimensions)}个维度有原文支持。" + (f"加权分{overall}/5。" if overall is not None else "存在无证据维度，不给出总分。") + "所有分数仅辅助人类复核。"
    return {"interviewId": interview_id, "reportId": str(report["id"]), "jobTitle": redact(str(service.required(connection, db.jobs, str(interview["job_id"]), "JOB_NOT_FOUND")["title"])),
            "candidateLabel": f"候选人 {str(person['id'])[:8]}", "status": str(interview["status"]), "revision": as_int(report, "revision"),
            "fixture": object_value(report["metadata"]).get("provider") == "fake", "overallScore": overall, "coverage": min(1.0, coverage),
            "overallSummary": summary, "dimensions": result_dimensions, "questions": questions,
            "evidence": [{"id": str(row["id"]), "turnId": str(row["turn_id"]), "turnSeq": as_int(next(turn for turn in turns if turn["id"] == row["turn_id"]), "seq"),
                          "competencyId": str(row["competency_id"]), "quote": redact(str(row["quote"]), str(person["full_name"]))} for row in evidence_rows],
            "highlights": [f"{row['competencyName']}：原文体现较完整的个人行动与验证。" for row in result_dimensions if row["score"] != "insufficient_evidence" and int(str(row["score"])) >= 4],
            "risks": [f"{row['competencyName']}：证据不足或采样差异，需人工补充核验。" for row in result_dimensions if row["score"] == "insufficient_evidence" or row["needsReview"]],
            "nextQuestions": [f"请补充一个体现「{row['competencyName']}」的岗位案例，说明个人行动、关键取舍与可核验结果。" for row in result_dimensions],
            "recommendation": recommendation, "recommendationReason": reason, "metadata": object_value(report["metadata"]), "campus": campus,
            "revisions": [{"id": str(row["id"]), "scoreId": str(row["score_id"]), "actorId": str(row["actor_id"]),
                           "actorName": cast(str | None, row["actor_name"]), "oldValue": str(row["old_value"]), "newValue": str(row["new_value"]),
                           "reason": redact(str(row["reason"]), str(person["full_name"])), "at": db.iso(row["created_at"])} for row in revisions]}


def generate_report(service: Service, connection: StorageSession, interview_id: str, rerun: bool, actor: Actor) -> Result:
    interview = service.interview(connection, interview_id, True)
    existing = db.rows(connection, select(db.reports).where(db.reports.c.interview_id == interview_id))
    if existing and not rerun:
        return Result(report_document(service, connection, interview_id))
    if interview["status"] not in {"scoring", "report_ready"}:
        raise DomainError("RESOURCE_CONFLICT", "请先结束面试；已复核报告不能重跑")
    score_rows = db.rows(connection, select(db.scores).where(db.scores.c.interview_id == interview_id))
    has_revisions = db.exists(connection, select(db.score_revisions.c.id).where(db.score_revisions.c.score_id.in_([str(row['id']) for row in score_rows])).limit(1))
    if has_revisions or interview.get("graduate_verification"):
        raise DomainError("RESOURCE_CONFLICT", "已有人工操作，不能重跑覆盖")
    person = service.candidate(connection, str(interview["candidate_id"]))
    questions = [row for row in service.question_rows(connection, interview_id) if row["assessment_mode"] == "scored"]
    question_ids = {row["id"] for row in questions}
    original_turns = [row for row in service.turn_rows(connection, interview_id) if row["question_id"] in question_ids]
    cleaned_turns: list[Object] = [{"id": str(row["id"]), "questionId": cast(str | None, row["question_id"]), "seq": as_int(row, "seq"),
                                  "role": str(row["role"]), "content": assessment_text(str(row["content"]), str(person["full_name"]))} for row in original_turns]
    dimensions = service.dimensions(connection, str(interview["job_id"]))
    context: Object = {"jobSummary": assessment_text(str(service.required(connection, db.jobs, str(interview["job_id"]), "JOB_NOT_FOUND")["jd_text"]))[:1800],
                       "competencies": dimensions, "questions": [{"id": str(row["id"]), "competencyId": str(row["competency_id"]), "seq": as_int(row, "seq"), "prompt": str(row["prompt"])} for row in questions], "turns": cleaned_turns}
    fixture = fixture_assessment(context)
    samples = [
        service.gateway.structured("assessment", scoring_prompt(context), AssessmentSample, fixture.payload())
        for _ in range(2)
    ]
    # Nothing is erased until both validated generations have succeeded.
    revision = as_int(existing[0], "revision") + 1 if existing else 1
    db.command(connection, db.scores.delete().where(db.scores.c.interview_id == interview_id))
    db.command(connection, db.evidence.delete().where(db.evidence.c.interview_id == interview_id))
    db.command(connection, db.reports.delete().where(db.reports.c.interview_id == interview_id))
    assessments: list[Object] = []
    for question in questions:
        sample_values: list[str] = []
        citations: dict[tuple[str, str], str] = {}
        needs_review = False
        for sample in samples:
            matching = [item for item in sample.data.questions if item.question_id == question["id"]]
            value: ScoreValue = "insufficient_evidence"
            if len(matching) != 1:
                needs_review = True
            else:
                proposed = matching[0]
                valid: list[tuple[str, str]] = []
                for citation in proposed.evidence:
                    original = next((turn for turn in original_turns if turn["id"] == citation.turn_id and turn["question_id"] == question["id"] and turn["role"] == "candidate"), None)
                    cleaned = next((turn for turn in cleaned_turns if turn["id"] == citation.turn_id), None)
                    if original and cleaned and citation.quote in str(original["content"]) and citation.quote in str(cleaned["content"]) and not INJECTION.search(citation.quote):
                        guard_output(citation.quote)
                        valid.append((citation.turn_id, citation.quote))
                if proposed.score != "insufficient_evidence" and valid and len(valid) == len(proposed.evidence):
                    value = proposed.score
                    for valid_citation in valid:
                        citations.setdefault(valid_citation, db.identifier())
                elif proposed.score != "insufficient_evidence":
                    needs_review = True
            sample_values.append(value)
        numeric = all(value != "insufficient_evidence" for value in sample_values)
        final_value = str(min(map(int, sample_values))) if numeric else "insufficient_evidence"
        needs_review |= (numeric and abs(int(sample_values[0]) - int(sample_values[1])) > 1) or len(set(sample_values)) > 1
        citation_ids: list[str] = []
        if numeric:
            for (turn_id, quote), identity in citations.items():
                db.insert(connection, db.evidence, {"id": identity, "interview_id": interview_id, "turn_id": turn_id,
                          "competency_id": question["competency_id"], "quote": quote})
                citation_ids.append(identity)
        assessments.append({"questionId": str(question["id"]), "seq": as_int(question, "seq"), "competencyId": str(question["competency_id"]),
                            "score": final_value, "sampleValues": sample_values, "needsReview": needs_review,
                            "rationale": "按岗位BARS与原文行为评分。" if numeric else "缺少可验证的原文，不补全、不编造。", "evidenceIds": citation_ids})
    dimension_results: list[Object] = []
    for dimension in dimensions:
        matches = [row for row in assessments if row["competencyId"] == dimension["id"]]
        numeric_matches = [row for row in matches if row["score"] != "insufficient_evidence"]
        dimension_value = str(math.floor(sum(int(str(row["score"])) for row in numeric_matches) / len(numeric_matches) + 0.5)) if numeric_matches else "insufficient_evidence"
        evidence_ids = [str(identity) for row in numeric_matches for identity in cast(list[str], row["evidenceIds"])]
        score = db.insert(connection, db.scores, {"interview_id": interview_id, "competency_id": dimension["id"],
                         "value": dimension_value, "numeric_value": int(dimension_value) if dimension_value != "insufficient_evidence" else None,
                         "evidence_id": evidence_ids[0] if evidence_ids else None, "attempt": 1, "needs_review": any(bool(row["needsReview"]) for row in matches),
                         "rationale": "由已验证证据的逐题分等权聚合，无证据不当0分。", "model": service.gateway.model, "prompt_version": "python-assessment-v1"})
        dimension_results.append({"competencyId": dimension["id"], "competencyName": dimension["name"], "weight": dimension["weight"], "score": dimension_value,
                                  "scoreId": str(score["id"]), "rationale": str(score["rationale"]), "needsReview": bool(score["needs_review"]),
                                  "sampleValues": [str(math.floor(sum(int(cast(list[str], row["sampleValues"])[index]) for row in numeric_matches) / len(numeric_matches) + 0.5)) if numeric_matches else "insufficient_evidence" for index in range(2)], "evidenceIds": evidence_ids})
    for sample in samples:
        service.usage(connection, interview_id, "assessment", sample.usage, interview_id)
    usages = db.rows(connection, select(db.audit_logs).where(and_(db.audit_logs.c.interview_id == interview_id, db.audit_logs.c.action == "llm.usage")))
    prompt_tokens = sum(int(str(object_value(row["metadata"]).get("promptTokens", 0))) for row in usages)
    completion_tokens = sum(int(str(object_value(row["metadata"]).get("completionTokens", 0))) for row in usages)
    metadata: Object = {"provider": service.gateway.name, "model": service.gateway.model, **service.gateway.usage(prompt_tokens, completion_tokens),
                        "generatedAt": db.iso(db.now()), "transcriptRedacted": True, "samplingRuns": 2,
                        "costBasis": "fixture_free" if service.gateway.name == "fake" else "configured_rates" if service.settings.input_price is not None else "unpriced_internal",
                        "usageEstimated": service.gateway.name == "fake", "transcriptHash": json_hash(cleaned_turns)}
    db.insert(connection, db.reports, {"interview_id": interview_id, "overall_summary": "已按岗位维度校验证据。", "dimension_scores": dimension_results,
              "question_scores": assessments, "revision": revision, "highlights": [], "risks": [], "next_questions": [], "recommendation": "mixed",
              "recommendation_reason": "供人工复核", "metadata": metadata, "retained_until": interview["retained_until"], "prompt_version": "python-assessment-v1"})
    db.update(connection, db.interviews, interview_id, status="report_ready")
    events.append_event(connection, interview_id, "score_computed",
                        {"dimensionCount": len(dimension_results), "revision": revision})
    events.append_event(connection, interview_id, "report_generated",
                        {"revision": revision, "recommendation": "mixed"})
    events.append_event(connection, interview_id, "state_changed",
                        {"from": str(interview["status"]), "to": "report_ready", "via": "score"})
    service.audit(connection, "report.generated", interview_id, {"revision": revision, "transcriptHash": metadata["transcriptHash"]}, actor, interview_id)
    return Result(report_document(service, connection, interview_id))


def revise_score(service: Service, connection: StorageSession, score_id: str, body: RevisionInput, actor: Actor) -> Result:
    score = service.required(connection, db.scores, score_id, "INTERVIEW_NOT_FOUND")
    identity = str(score["interview_id"])
    interview = service.interview(connection, identity, True)
    report = db.rows(connection, select(db.reports).where(db.reports.c.interview_id == identity))[0]
    if body.expected_revision != report["revision"]:
        raise DomainError("RESOURCE_CONFLICT", "报告已更新，请刷新后重试")
    if body.value != "insufficient_evidence":
        evidence = service.required(connection, db.evidence, body.evidence_id or "00000000-0000-0000-0000-000000000000", "VALIDATION_FAILED")
        if evidence["interview_id"] != identity or evidence["competency_id"] != score["competency_id"]:
            raise DomainError("VALIDATION_FAILED", "改分证据必须属于同场同维度")
    reason = redact(body.reason, str(service.candidate(connection, str(interview["candidate_id"]))["full_name"]))
    db.insert(connection, db.score_revisions, {"score_id": score_id, "actor_id": actor.id, "actor_name": actor.name,
              "old_value": score["value"], "new_value": body.value, "reason": reason})
    db.update(connection, db.scores, score_id, value=body.value, numeric_value=int(body.value) if body.value != "insufficient_evidence" else None,
              evidence_id=body.evidence_id if body.value != "insufficient_evidence" else None)
    db.update(connection, db.reports, str(report["id"]), revision=as_int(report, "revision") + 1)
    db.update(connection, db.interviews, identity, status="report_ready")
    service.audit(connection, "score.revised", identity, {"oldValue": str(score["value"]), "newValue": body.value, "reason": reason}, actor, identity)
    return Result(report_document(service, connection, identity))


def verify_graduate(service: Service, connection: StorageSession, identity: str, body: GraduateInput, actor: Actor) -> Result:
    interview = service.interview(connection, identity, True)
    report = db.rows(connection, select(db.reports).where(db.reports.c.interview_id == identity))
    if interview["recruitment_track"] != "graduate_campus" or not report or interview["status"] not in {"report_ready", "reviewed"}:
        raise DomainError("RESOURCE_CONFLICT", "请先生成校招报告")
    if report[0]["revision"] != body.expected_revision:
        raise DomainError("RESOURCE_CONFLICT", "报告已更新，请刷新")
    verification: Object = {**body.payload(), "policyVersion": GRADUATE_POLICY, "reviewerId": actor.id,
                             "reviewerName": actor.name, "reviewedAt": db.iso(db.now())}
    verification.pop("expectedRevision", None)
    for key in ["cet4Reference", "transcriptReference", "note"]:
        verification[key] = redact(str(verification[key]))
    db.update(connection, db.interviews, identity, graduate_verification=verification, status="report_ready")
    db.update(connection, db.reports, str(report[0]["id"]), revision=body.expected_revision + 1)
    service.audit(connection, "graduate.verified", identity, {"old": interview.get("graduate_verification"), "current": verification}, actor, identity)
    return Result(report_document(service, connection, identity))


def review_report(service: Service, connection: StorageSession, identity: str, body: ReviewInput, actor: Actor) -> Result:
    document = report_document(service, connection, identity)
    if document["revision"] != body.expected_revision:
        raise DomainError("RESOURCE_CONFLICT", "报告已更新，请刷新")
    campus = document.get("campus")
    if campus:
        qualification = object_value(campus)
        if qualification["status"] == "pending" or qualification["mandatoryAsked"] != qualification["mandatoryTotal"]:
            raise DomainError("RESOURCE_CONFLICT", "资格尚待核验或必问未全部触达")
    db.update(connection, db.interviews, identity, status="reviewed")
    service.audit(connection, "report.reviewed", identity, {"note": redact(body.note)}, actor, identity)
    return Result(report_document(service, connection, identity))
