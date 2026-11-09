from __future__ import annotations

import re

from .auth import Actor
from .contracts import CandidateCreate, FormalInterviewCreate, InterviewCreate, JobCreate, Object
from .domain import FORMAL_CAMPUS_PLAN, FORMAL_CAMPUS_TOPICS, fixture_competencies
from .errors import DomainError
from .repository import StorageSession
from .safety import PROTECTED, assessment_text, safe_question
from .service import Result, Service


def excerpt(source: str, name: str = "", preferred: str = "") -> str:
    pieces = [part.strip(" \t·•-：:，,") for part in re.split(r"[\n。！？!?；;]", assessment_text(source, name))]
    usable = [piece for piece in pieces if len(piece) >= 6 and not PROTECTED.search(piece) and "[" not in piece]
    for piece in sorted(usable, key=lambda item: bool(preferred and preferred in item), reverse=True):
        try:
            return safe_question(piece[:90])
        except DomainError:
            continue
    raise DomainError("VALIDATION_FAILED", "岗位 JD 和简历均需包含可用于提问的岗位职责或项目经历")


def create(service: Service, connection: StorageSession, body: FormalInterviewCreate, actor: Actor) -> Result:
    jd = excerpt(body.jd_text, preferred="负责")
    resume = excerpt(body.resume_text, body.candidate_name, preferred="项目")
    job = JobCreate(title=body.title, jd_text=body.jd_text, recruitment_track="graduate_campus")
    job_id = str(service.create_job(connection, job, actor).payload["id"])
    rubric = fixture_competencies(False)
    labels = [
        ("固定题表现", "回答岗位固定问题时的个人行动与结果"),
        ("岗位理解", "理解岗位职责并给出可验证的执行思路"),
        ("简历实践", "说明简历项目中的个人贡献与结果"),
        ("经验迁移", "将简历经验应用到岗位职责并说明验证方法"),
    ]
    for dimension, (label, description) in zip(rubric.competencies, labels, strict=True):
        dimension.name = label
        dimension.description = description
    service.save_competencies(connection, job_id, rubric, True, actor)
    candidate_id = str(service.create_candidate(connection, CandidateCreate(job_id=job_id, full_name=body.candidate_name), actor).payload["id"])
    person = service.candidate(connection, candidate_id)
    dimensions = service.dimensions(connection, job_id)
    prompts = [
        (1, f"岗位 JD 提到「{jd}」。如果由你负责，你会怎样着手并验证结果？"),
        (2, f"简历中提到「{resume}」。请说明你个人负责的部分、做法和结果。"),
        (3, f"结合刚才的经历，如果要承担「{jd}」，你会复用哪些做法，又会怎样验证它们在新岗位上有效？"),
    ]
    plan: list[Object] = [
        {"competencyId": dimensions[0]["id"], "prompt": safe_question(str(topic["prompt"])),
         "intent": labels[0][1] if topic["mode"] == "scored" else "记录岗位事实，资格由人工核验",
         "followups": [], "topicKey": topic["key"], "mandatory": True, "assessmentMode": topic["mode"]}
        for topic in FORMAL_CAMPUS_TOPICS
    ]
    plan.extend(
        {"competencyId": dimensions[dimension]["id"],
         "prompt": safe_question(question), "intent": labels[dimension][1],
         "followups": [], "topicKey": None, "mandatory": False, "assessmentMode": "scored"}
        for dimension, question in prompts
    )
    budget, extra = divmod(body.duration_minutes * 57, len(plan))
    for index, question in enumerate(plan, 1):
        question.update(seq=index, timeBudgetSec=budget + int(index <= extra))
    interview = InterviewCreate(job_id=job_id, candidate_id=candidate_id, duration_minutes=body.duration_minutes)
    return service.invite(connection, interview, person, job.recruitment_track, plan, FORMAL_CAMPUS_PLAN, actor)
