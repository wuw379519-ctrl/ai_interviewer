from __future__ import annotations

from .contracts import Object

STATUS = {"VALIDATION_FAILED": 400, "UNAUTHORIZED": 401, "FORBIDDEN": 403,
          "JOB_NOT_FOUND": 404, "CANDIDATE_NOT_FOUND": 404, "INTERVIEW_NOT_FOUND": 404,
          "CANDIDATE_DELETED": 410, "RATE_LIMITED": 429, "NOT_READY": 503, "SPEECH_UNAVAILABLE": 503,
          "LLM_PROVIDER_UNAVAILABLE": 502, "LLM_STRUCTURED_OUTPUT_INVALID": 502, "INTERNAL_ERROR": 500}


class DomainError(Exception):
    def __init__(self, code: str, message: str, details: Object | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.details = code, message, details
        self.status = STATUS.get(code, 409)

    def payload(self) -> Object:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}
