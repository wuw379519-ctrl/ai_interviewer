from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, field_validator, model_validator
from pydantic.alias_generators import to_camel

Object = dict[str, object]


def json_object(value: object) -> Object:
    return {key: item for key, item in TypeAdapter(dict[str, JsonValue]).validate_python(value).items()}
ScoreValue = Literal["1", "2", "3", "4", "5", "insufficient_evidence"]
Track = Literal["general", "graduate_campus"]
Status = Literal["created", "invited", "consented", "warmup", "interviewing", "wrapping_up",
                 "scoring", "report_ready", "reviewed", "cancelled"]


def uuid_text(value: str) -> str:
    return str(UUID(value))


Identifier = Annotated[str, AfterValidator(uuid_text)]
ShortReason = Annotated[str, Field(min_length=4, max_length=600)]


class Contract(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", strict=True)

    def payload(self) -> Object:
        return self.model_dump(mode="json", by_alias=True)


class JobCreate(Contract):
    title: str = Field(min_length=2, max_length=120)
    jd_text: str = Field(min_length=30, max_length=20000)
    recruitment_track: Track = "general"


class CandidateCreate(Contract):
    job_id: Identifier
    full_name: str = Field(min_length=1, max_length=80)
    email: str | None = Field(default=None, max_length=200, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class InterviewCreate(Contract):
    job_id: Identifier
    candidate_id: Identifier
    duration_minutes: Literal[15, 30, 45]
    mode: Literal["text", "voice"] = "text"
    camera_required: bool | None = None


class FormalInterviewCreate(Contract):
    title: str = Field(min_length=2, max_length=120)
    candidate_name: str = Field(min_length=1, max_length=80)
    jd_text: str = Field(min_length=30, max_length=20000)
    resume_text: str = Field(min_length=20, max_length=30000)
    duration_minutes: Literal[15, 30, 45] = 15

    @field_validator("title", "candidate_name", "jd_text", "resume_text", mode="before")
    @classmethod
    def strip_input(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class Anchor(Contract):
    level: int = Field(ge=1, le=5)
    anchor: str = Field(min_length=1, max_length=500)


class Competency(Contract):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=1000)
    weight: float = Field(gt=0, le=1)
    bars: list[Anchor] = Field(min_length=5, max_length=5)

    @model_validator(mode="after")
    def levels(self) -> Self:
        if {row.level for row in self.bars} != {1, 2, 3, 4, 5}:
            raise ValueError("BARS必须包含互不相同的1至5级")
        return self


class CompetencySet(Contract):
    competencies: list[Competency] = Field(min_length=4, max_length=6)

    @model_validator(mode="after")
    def weights(self) -> Self:
        if sum(round(row.weight * 10000) for row in self.competencies) != 10000:
            raise ValueError("胜任力正权重之和必须为100%")
        if len({row.name for row in self.competencies}) != len(self.competencies):
            raise ValueError("维度名称不得重复")
        return self


class Experience(Contract):
    model_config = ConfigDict(extra="ignore")
    company: str
    title: str
    start: str | None = None
    end: str | None = None
    highlights: list[str] = Field(default_factory=list)


class Project(Contract):
    model_config = ConfigDict(extra="ignore")
    name: str
    detail: str


class ResumeProfile(Contract):
    # Explicit whitelist: unknown/protected fields cannot enter the structured profile.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore", strict=True)
    summary: str = ""
    experiences: list[Experience] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)


class Claim(Contract):
    id: str
    text: str = Field(min_length=1)
    source_section: str = Field(min_length=1)
    related_competency_hint: str | None = None


class ResumeExtraction(Contract):
    profile: ResumeProfile
    claims: list[Claim] = Field(max_length=30)


class ResumeText(Contract):
    text: str = Field(min_length=20, max_length=30000)


class ConsentInput(Contract):
    accepted: Literal[True]
    consent_version: str = Field(min_length=1, max_length=100)


class MediaInput(Contract):
    camera_active: bool
    microphone_active: bool
    reason: Literal["check", "heartbeat", "device_lost", "paused", "released"]
    text_fallback: bool | None = None


class TurnInput(Contract):
    action: Literal["answer", "repeat", "skip"]
    content: str | None = Field(default=None, max_length=4000)
    expected_question_seq: int | None = Field(default=None, ge=1)


class PauseInput(Contract):
    paused: bool


class LoginInput(Contract):
    username: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=200)


class FeishuOAuthInput(Contract):
    code: str = Field(min_length=1, max_length=512)
    state: str = Field(min_length=1, max_length=512)


class EmptyInput(Contract):
    pass


class ScoreInput(Contract):
    rerun: bool = False


class RevisionInput(Contract):
    value: ScoreValue
    reason: ShortReason
    expected_revision: int = Field(gt=0)
    evidence_id: Identifier | None = None


class ReviewInput(Contract):
    expected_revision: int = Field(gt=0)
    note: ShortReason


class PrintInput(Contract):
    expected_revision: int = Field(gt=0)


class GraduateInput(Contract):
    expected_revision: int = Field(gt=0)
    cet4_score: int | None = Field(ge=0, le=710)
    cet4_reference: str = Field(max_length=200)
    failed_graduate_courses: int | None = Field(ge=0, le=200)
    transcript_reference: str = Field(max_length=200)
    note: ShortReason

    @model_validator(mode="after")
    def references(self) -> Self:
        if self.cet4_score is not None and len(self.cet4_reference.strip()) < 3:
            raise ValueError("已核验四级分数需要成绩报告来源")
        if self.failed_graduate_courses is not None and len(self.transcript_reference.strip()) < 3:
            raise ValueError("已核验挂科数需要完整成绩单来源")
        return self


class RetentionInput(Contract):
    retention_days: int = Field(ge=1, le=90)
    expected_revision: int = Field(gt=0)
    reason: str = Field(min_length=4, max_length=300)


class DeleteInput(Contract):
    confirm_candidate_id: Identifier
    reason: str = Field(min_length=4, max_length=300)


class CleanupInput(Contract):
    preview_token: str = Field(min_length=1, max_length=1200)
    reason: str = Field(min_length=4, max_length=300)


class Citation(Contract):
    turn_id: Identifier
    quote: str = Field(min_length=2, max_length=160)


class SampleQuestion(Contract):
    question_id: Identifier
    score: ScoreValue
    rationale: str = Field(min_length=1, max_length=400)
    evidence: list[Citation] = Field(max_length=2)


class AssessmentSample(Contract):
    questions: list[SampleQuestion] = Field(max_length=24)


class PlanQuestion(Contract):
    competency_id: Identifier
    prompt: str = Field(min_length=10, max_length=500)
    intent: str = Field(min_length=1, max_length=300)


class PlanDraft(Contract):
    questions: list[PlanQuestion] = Field(min_length=8, max_length=18)


class SpeechOutput(Contract):
    text: str = Field(min_length=1, max_length=4000)


class QuestionAssessment(Contract):
    question_id: str
    seq: int
    competency_id: str
    score: ScoreValue
    rationale: str
    needs_review: bool
    sample_values: list[ScoreValue] = Field(min_length=2, max_length=2)
    evidence_ids: list[str]


class DimensionAssessment(Contract):
    competency_id: str
    competency_name: str
    weight: float = Field(ge=0, le=1)
    score: ScoreValue
    score_id: str
    rationale: str
    needs_review: bool
    sample_values: list[ScoreValue] = Field(max_length=2)
    evidence_ids: list[str]

    @model_validator(mode="after")
    def cited(self) -> Self:
        if (self.score == "insufficient_evidence") != (not self.evidence_ids):
            raise ValueError("数值分必须有原文证据；证据不足不能附会引用")
        return self


class Evidence(Contract):
    id: Identifier
    turn_id: Identifier
    turn_seq: int = Field(gt=0)
    competency_id: Identifier
    quote: str = Field(min_length=1)


class ReportMetadata(Contract):
    model_config = ConfigDict(extra="ignore")
    provider: str
    model: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)
    generated_at: str
    transcript_redacted: bool
    sampling_runs: int = Field(ge=1, le=2)
    cost_basis: Literal["fixture_free", "configured_rates", "unpriced_internal"] = "unpriced_internal"
    usage_estimated: bool = True
    transcript_hash: str = ""

    @model_validator(mode="after")
    def tokens_match(self) -> Self:
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("token总数与明细不一致")
        return self


class ScoreRevision(Contract):
    id: Identifier
    score_id: Identifier
    actor_id: str
    actor_name: str | None
    old_value: ScoreValue
    new_value: ScoreValue
    reason: str
    at: str


class ProctorRiskItem(Contract):
    """Structured proctoring risk — never enters scoring evidence; humans decide."""

    code: str = Field(min_length=2, max_length=80)
    severity: Literal["hint", "review"]
    message: str = Field(min_length=4, max_length=600)
    signal_count: int = Field(ge=0, default=0)
    affects_score: bool = False
    for_human_review: bool = True


class ReportDocument(Contract):
    interview_id: Identifier
    report_id: Identifier
    job_title: str
    candidate_label: str
    status: Literal["report_ready", "reviewed"]
    revision: int = Field(gt=0)
    fixture: bool
    overall_score: float | None = Field(ge=1, le=5)
    coverage: float = Field(ge=0, le=1)
    overall_summary: str
    dimensions: list[DimensionAssessment]
    questions: list[QuestionAssessment]
    evidence: list[Evidence]
    highlights: list[str]
    risks: list[str]
    risk_items: list[ProctorRiskItem] = Field(default_factory=list)
    next_questions: list[str]
    recommendation: Literal["strong_yes", "yes", "mixed", "no"]
    recommendation_reason: str
    metadata: ReportMetadata
    revisions: list[ScoreRevision]
    campus: Object | None = None


class ErrorDetail(Contract):
    code: str
    message: str
    details: Object | list[Object] | None = None


class ErrorEnvelope(Contract):
    error: ErrorDetail
