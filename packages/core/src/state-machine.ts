import { DomainError } from "./errors";
import { INTERVIEW_STATES, type InterviewStatus } from "./schemas";

/**
 * 面试状态机。
 *
 * created → invited → consented → warmup → interviewing → wrapping_up → scoring → report_ready → reviewed
 *                                                                        ↘ cancelled（任意未终结态可取消/撤回）
 *
 * 两条硬约束（对应 P0 合规要求）：
 * 1. 进入 consented 必须携带有效同意记录（同意文本版本 + 时间戳），否则拒绝迁移；
 * 2. 只有在 interviewing / wrapping_up 允许写入候选人回答；consented 之前不得采集任何回答内容。
 */

export { INTERVIEW_STATES };
export type { InterviewStatus };

export const ALLOWED_TRANSITIONS: Readonly<Record<InterviewStatus, readonly InterviewStatus[]>> = {
  created: ["invited", "cancelled"],
  invited: ["consented", "cancelled"],
  consented: ["warmup", "cancelled"],
  warmup: ["interviewing", "cancelled"],
  interviewing: ["wrapping_up", "cancelled"],
  wrapping_up: ["scoring"],
  scoring: ["report_ready"],
  report_ready: ["reviewed"],
  reviewed: [],
  cancelled: [],
};

/** 只有这两个状态允许落库候选人回答。 */
export const RECORDABLE_STATES: readonly InterviewStatus[] = ["interviewing", "wrapping_up"];

/** 同意之前的所有状态：任何回答采集请求都要报 CONSENT_REQUIRED，而不是静默丢弃。 */
const PRE_CONSENT_STATES: readonly InterviewStatus[] = ["created", "invited"];

export interface TransitionContext {
  /** 是否已存在有效同意记录（consents 表中的一行）。 */
  hasConsent?: boolean;
  /** 同意文本版本，进入 consented 时必填，便于日后证明「同意的是哪一版条款」。 */
  consentVersion?: string;
}

export interface TransitionResult {
  from: InterviewStatus;
  to: InterviewStatus;
  /** false 表示目标状态与当前相同（幂等调用），调用方不应重复写审计日志。 */
  changed: boolean;
}

export function isInterviewStatus(value: unknown): value is InterviewStatus {
  return typeof value === "string" && (INTERVIEW_STATES as readonly string[]).includes(value);
}

export function assertInterviewStatus(value: unknown): asserts value is InterviewStatus {
  if (!isInterviewStatus(value)) {
    throw new DomainError("STATE_INVALID", `未知的面试状态: ${String(value)}`, { value });
  }
}

export function nextStates(from: InterviewStatus): readonly InterviewStatus[] {
  return ALLOWED_TRANSITIONS[from];
}

export function isTerminal(state: InterviewStatus): boolean {
  return ALLOWED_TRANSITIONS[state].length === 0;
}

export function canTransition(from: InterviewStatus, to: InterviewStatus): boolean {
  return ALLOWED_TRANSITIONS[from].includes(to);
}

/**
 * 校验并返回迁移结果。非法迁移抛 DomainError(STATE_INVALID_TRANSITION)。
 * 同状态调用视为幂等成功（changed=false），方便断线重连时重复提交「start」。
 */
export function assertTransition(
  from: InterviewStatus,
  to: InterviewStatus,
  context: TransitionContext = {},
): TransitionResult {
  assertInterviewStatus(from);
  assertInterviewStatus(to);

  if (from === to) {
    if (to === "consented" && !isConsentSatisfied(context)) {
      throw new DomainError("CONSENT_REQUIRED", "进入 consented 需要有效同意记录（版本 + 时间戳）", { from, to });
    }
    return { from, to, changed: false };
  }

  if (!canTransition(from, to)) {
    throw new DomainError("STATE_INVALID_TRANSITION", `不允许的状态迁移: ${from} → ${to}`, {
      from,
      to,
      allowed: ALLOWED_TRANSITIONS[from],
    });
  }

  if (to === "consented" && !isConsentSatisfied(context)) {
    throw new DomainError("CONSENT_REQUIRED", "进入 consented 需要有效同意记录（版本 + 时间戳）", { from, to });
  }

  return { from, to, changed: true };
}

function isConsentSatisfied(context: TransitionContext): boolean {
  return context.hasConsent === true && typeof context.consentVersion === "string" && context.consentVersion.length > 0;
}

/**
 * 写入候选人回答（POST /interviews/:id/turns）前的门禁。
 * 事前状态：CONSENT_REQUIRED（还没同意）；事后状态：INTERVIEW_CLOSED（面试已结束）。
 */
export function assertCanRecordAnswer(state: InterviewStatus): void {
  assertInterviewStatus(state);

  if (PRE_CONSENT_STATES.includes(state)) {
    throw new DomainError("CONSENT_REQUIRED", "候选人尚未完成知情同意，禁止采集任何回答内容", { state });
  }

  if (!RECORDABLE_STATES.includes(state)) {
    throw new DomainError("INTERVIEW_CLOSED", `当前状态 ${state} 不接受新的回答`, { state });
  }
}

export function canRecordAnswer(state: InterviewStatus): boolean {
  return RECORDABLE_STATES.includes(state);
}
