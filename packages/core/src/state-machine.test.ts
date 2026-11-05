import { describe, expect, it } from "vitest";
import { DomainError } from "./errors";
import { INTERVIEW_STATES, type InterviewStatus } from "./schemas";
import {
  ALLOWED_TRANSITIONS,
  assertCanRecordAnswer,
  assertTransition,
  canRecordAnswer,
  canTransition,
  isTerminal,
  nextStates,
} from "./state-machine";

const SPEC_STATES: InterviewStatus[] = [
  "created",
  "invited",
  "consented",
  "warmup",
  "interviewing",
  "wrapping_up",
  "scoring",
  "report_ready",
  "reviewed",
];

const HAPPY_PATH: InterviewStatus[] = [
  "created",
  "invited",
  "consented",
  "warmup",
  "interviewing",
  "wrapping_up",
  "scoring",
  "report_ready",
  "reviewed",
];

function expectDomainError(fn: () => unknown, code: string): void {
  try {
    fn();
  } catch (error) {
    expect(error).toBeInstanceOf(DomainError);
    expect((error as DomainError).code).toBe(code);
    return;
  }
  throw new Error(`期望抛出 ${code}，实际没有抛错`);
}

describe("状态机拓扑", () => {
  it("覆盖规格里的 9 个状态，且额外只有 cancelled 一个扩展态", () => {
    for (const state of SPEC_STATES) {
      expect(INTERVIEW_STATES).toContain(state);
      expect(ALLOWED_TRANSITIONS[state]).toBeDefined();
    }
    const extras = INTERVIEW_STATES.filter((s) => !SPEC_STATES.includes(s));
    expect(extras).toEqual(["cancelled"]);
  });

  it("每个状态的合法目标都在状态集合内，且不会指向自己", () => {
    for (const state of INTERVIEW_STATES) {
      for (const target of ALLOWED_TRANSITIONS[state]) {
        expect(INTERVIEW_STATES).toContain(target);
        expect(target).not.toBe(state);
      }
    }
  });

  it("主路径逐步可达", () => {
    for (let i = 0; i < HAPPY_PATH.length - 1; i += 1) {
      const from = HAPPY_PATH[i]!;
      const to = HAPPY_PATH[i + 1]!;
      expect(canTransition(from, to)).toBe(true);
    }
  });

  it("所有状态都能从 created 走到（可达性）", () => {
    const seen = new Set<InterviewStatus>(["created"]);
    const queue: InterviewStatus[] = ["created"];
    while (queue.length > 0) {
      const current = queue.shift()!;
      for (const target of ALLOWED_TRANSITIONS[current]) {
        if (!seen.has(target)) {
          seen.add(target);
          queue.push(target);
        }
      }
    }
    expect([...seen].sort()).toEqual([...INTERVIEW_STATES].sort());
  });

  it("终态不可再迁移，且 reviewed / cancelled 是终态", () => {
    expect(isTerminal("reviewed")).toBe(true);
    expect(isTerminal("cancelled")).toBe(true);
    expect(isTerminal("interviewing")).toBe(false);
    expect(nextStates("reviewed")).toEqual([]);
  });

  it("禁止跳步与倒流", () => {
    const illegal: Array<[InterviewStatus, InterviewStatus]> = [
      ["created", "consented"],
      ["created", "interviewing"],
      ["invited", "warmup"],
      ["warmup", "scoring"],
      ["interviewing", "scoring"],
      ["scoring", "interviewing"],
      ["report_ready", "interviewing"],
      ["reviewed", "created"],
      ["cancelled", "created"],
    ];
    for (const [from, to] of illegal) {
      expect(canTransition(from, to)).toBe(false);
      expectDomainError(() => assertTransition(from, to, { hasConsent: true, consentVersion: "v1" }), "STATE_INVALID_TRANSITION");
    }
  });

  it("任意未终结态都能取消（候选人撤回同意）", () => {
    for (const state of ["created", "invited", "consented", "warmup", "interviewing"] as const) {
      expect(canTransition(state, "cancelled")).toBe(true);
    }
    for (const state of ["wrapping_up", "scoring", "report_ready", "reviewed"] as const) {
      expect(canTransition(state, "cancelled")).toBe(false);
    }
  });
});

describe("迁移执行", () => {
  it("合法迁移返回 changed=true", () => {
    const result = assertTransition("created", "invited");
    expect(result).toEqual({ from: "created", to: "invited", changed: true });
  });

  it("同状态重复调用幂等（断线重连重复 start 不报错）", () => {
    const result = assertTransition("interviewing", "interviewing");
    expect(result.changed).toBe(false);
  });

  it("进入 consented 必须带同意记录", () => {
    expectDomainError(() => assertTransition("invited", "consented"), "CONSENT_REQUIRED");
    expectDomainError(() => assertTransition("invited", "consented", { hasConsent: false, consentVersion: "v1" }), "CONSENT_REQUIRED");
    expectDomainError(() => assertTransition("invited", "consented", { hasConsent: true }), "CONSENT_REQUIRED");
    expectDomainError(
      () => assertTransition("invited", "consented", { hasConsent: true, consentVersion: "" }),
      "CONSENT_REQUIRED",
    );
    expect(assertTransition("invited", "consented", { hasConsent: true, consentVersion: "consent-2026-11" }).changed).toBe(true);
  });

  it("重复进入 consented 也要过同意门禁", () => {
    expectDomainError(() => assertTransition("consented", "consented"), "CONSENT_REQUIRED");
  });

  it("未知状态抛 STATE_INVALID", () => {
    expectDomainError(() => assertTransition("banana" as InterviewStatus, "invited"), "STATE_INVALID");
  });

  it("错误详情里带 allowed 列表，便于前端提示", () => {
    try {
      assertTransition("created", "scoring");
    } catch (error) {
      const details = (error as DomainError).details;
      expect(details).toMatchObject({ from: "created", to: "scoring" });
      expect(details?.allowed).toEqual(["invited", "cancelled"]);
    }
  });
});

describe("回答采集门禁（同意前不得采集）", () => {
  it("created / invited 状态禁止采集，报 CONSENT_REQUIRED", () => {
    for (const state of ["created", "invited"] as const) {
      expect(canRecordAnswer(state)).toBe(false);
      expectDomainError(() => assertCanRecordAnswer(state), "CONSENT_REQUIRED");
    }
  });

  it("consented / warmup 已同意但尚未开问，不落回答（保留），按 INTERVIEW_CLOSED 拒绝", () => {
    for (const state of ["consented", "warmup"] as const) {
      expect(canRecordAnswer(state)).toBe(false);
      expectDomainError(() => assertCanRecordAnswer(state), "INTERVIEW_CLOSED");
    }
  });

  it("只有 interviewing / wrapping_up 允许写入回答", () => {
    expect(canRecordAnswer("interviewing")).toBe(true);
    expect(canRecordAnswer("wrapping_up")).toBe(true);
    expect(() => assertCanRecordAnswer("interviewing")).not.toThrow();
    expect(() => assertCanRecordAnswer("wrapping_up")).not.toThrow();
  });

  it("结束后（scoring 及以后）拒绝写入", () => {
    for (const state of ["scoring", "report_ready", "reviewed", "cancelled"] as const) {
      expectDomainError(() => assertCanRecordAnswer(state), "INTERVIEW_CLOSED");
    }
  });
});
