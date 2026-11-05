import { describe, expect, it } from "vitest";
import { cacheOwnershipHint, deleteCandidateSchema, minimizedAuditMetadata, retentionDeadline, sanitizeAuditMetadata, updateRetentionSchema, assertRetentionCutoff } from "./governance";
import { consentForMedia } from "./media";
const id = "ceeb4fbf-502c-4d1b-bbd7-95065b16b622";
describe("数据治理领域规则", () => {
  it.each([1, 30, 90])("保留%i天且不延长上级资料期限", (days) => {
    const now = Date.now(), ceiling = new Date(now + 20000);
    expect(retentionDeadline(now, days).getTime()).toBe(now + days * 86400000); expect(retentionDeadline(now, days, ceiling)).toEqual(ceiling);
  });
  it.each([0, -1, 91, 1.5, NaN])("拒绝保留天数%s", (days) => expect(() => retentionDeadline(Date.now(), days)).toThrow());
  it.each(["text", "voice"] as const)("%s校招同意展示实际保留期并更新版本", (mode) => {
    const old = consentForMedia({ mode, cameraRequired: true, recruitmentTrack: "graduate_campus" });
    const next = consentForMedia({ mode, cameraRequired: true, recruitmentTrack: "graduate_campus", retentionDays: 30 });
    expect(next.text).toContain("30天"); expect(next.text).not.toMatch(/90\s*天/); expect(next.text).toContain("425"); expect(next.version).toContain("retention-30-v1"); expect(next.version).not.toBe(old.version);
  });
  it("保留90天沿用旧同意版本，拒绝未来清理截止时间", () => {
    expect(consentForMedia({ mode: "text", cameraRequired: false, retentionDays: 90 })).toEqual(consentForMedia({ mode: "text", cameraRequired: false }));
    expect(() => assertRetentionCutoff(new Date(Date.now() + 10000))).toThrow(); expect(() => assertRetentionCutoff(new Date(NaN))).toThrow();
  });
  it("日志递归脱敏手机号、邮箱、身份证与密钥，不误删token计数", () => {
    const clean = sanitizeAuditMetadata({ nested: { note: "13800138000 user@example.com 11010519491231002X", password: "secret-value" }, list: ["13900139000", 13700137000], promptTokens: 100, inviteToken: "invite-value" });
    expect(JSON.stringify(clean)).not.toMatch(/13800138000|13900139000|13700137000|user@example.com|11010519491231002X|secret-value|invite-value/); expect(clean.promptTokens).toBe(100);
  });
  it("删除后只保留数值改分与操作信封，不保留理由、引用或资格成绩", () => {
    expect(minimizedAuditMetadata("score.revised", { oldValue: "3", newValue: "4", reason: "独有回答原话" })).toEqual({ erased: true, oldValue: "3", newValue: "4" });
    expect(minimizedAuditMetadata("graduate.verified", { current: { cet4Score: 425, note: "证明来源" } })).toEqual({ erased: true });
  });
  it("客户端不能修改策略版本、伪造操作者或扩大90天上限", () => {
    expect(updateRetentionSchema.safeParse({ retentionDays: 91, expectedRevision: 1, reason: "扩大保留期限" }).success).toBe(false);
    expect(updateRetentionSchema.safeParse({ retentionDays: 30, expectedRevision: 1, reason: "缩短保留期限", actorId: "forged" }).success).toBe(false);
    expect(deleteCandidateSchema.safeParse({ confirmCandidateId: id, reason: "响应候选人删除请求", actorId: "forged" }).success).toBe(false);
  });
  it.each([`POST /interviews/${id}/turns`, `PATCH /interviews/${id}/eligibility`])("由服务端路径识别缓存归属：%s", (scope) => expect(cacheOwnershipHint(scope, { interviewId: "forged" })).toEqual({ kind: "interview", id }));
  it("创建缓存按已校验响应归属，删除回执不关联已删除的个人内容", () => {
    expect(cacheOwnershipHint("POST /candidates", { id })).toEqual({ kind: "candidate", id });
    expect(cacheOwnershipHint(`POST /candidates/${id}/resume`, {})).toEqual({ kind: "candidate", id });
    expect(cacheOwnershipHint(`PATCH /scores/${id}`, {})).toEqual({ kind: "score", id });
    expect(cacheOwnershipHint("POST /interviews", { interviewId: id })).toEqual({ kind: "interview", id });
    expect(cacheOwnershipHint(`DELETE /candidates/${id}`, { candidateId: id })).toBeNull();
    expect(cacheOwnershipHint("POST /jobs", { id })).toBeNull();
  });
});
