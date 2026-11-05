/**
 * 统一错误码。API 错误体 { error: { code, message, details } } 中的 code 一律取自这里，
 * 日志与告警引用同一套码，排障时可直接 grep。
 */
export const ERROR_CODES = [
  // 状态机 / 流程
  "STATE_INVALID_TRANSITION",
  "STATE_INVALID",
  "STATE_TERMINAL",
  "CONSENT_REQUIRED",
  "INTERVIEW_CLOSED",
  // 输入校验
  "VALIDATION_FAILED",
  "COMPETENCY_WEIGHT_SUM_INVALID",
  "COMPETENCY_NOT_CONFIRMED",
  // 幂等
  "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_BODY",
  // 数据治理
  "CANDIDATE_NOT_FOUND",
  "JOB_NOT_FOUND",
  "RESOURCE_CONFLICT",
  "RATE_LIMITED",
  "MEDIA_REQUIRED",
  "SPEECH_UNAVAILABLE",
  "CANDIDATE_DELETED",
  "INTERVIEW_NOT_FOUND",
  "UNAUTHORIZED",
  "FORBIDDEN",
  "NOT_READY",
  // LLM
  "LLM_PROVIDER_UNAVAILABLE",
  "LLM_STRUCTURED_OUTPUT_INVALID",
  // 兜底
  "INTERNAL_ERROR",
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

export interface ErrorDetails {
  [key: string]: unknown;
}

export class DomainError extends Error {
  readonly code: ErrorCode;
  readonly details: ErrorDetails | undefined;

  constructor(code: ErrorCode, message: string, details?: ErrorDetails) {
    super(message);
    this.name = "DomainError";
    this.code = code;
    this.details = details;
  }

  toJSON(): { error: { code: ErrorCode; message: string; details: ErrorDetails | null } } {
    return {
      error: {
        code: this.code,
        message: this.message,
        details: this.details ?? null,
      },
    };
  }
}

export function isDomainError(value: unknown): value is DomainError {
  return value instanceof DomainError;
}
