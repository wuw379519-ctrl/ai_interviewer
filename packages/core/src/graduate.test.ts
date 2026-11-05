import { describe, expect, it } from "vitest";
import { buildGraduatePlan, graduateEligibility, graduateCoverage, graduateVerificationInputSchema, GRADUATE_POLICY_VERSION, GRADUATE_TOPICS, graduatePlanVersion, statusAfterQualificationAmendment, type GraduateVerification } from "./graduate";
import { decideNextAction } from "./conversation";
import { consentForMedia } from "./media";
import type { PlanCompetency } from "./plan";
import { assertSafeQuestion } from "./intake";

function dimensions(count: number): PlanCompetency[] {
  return Array.from({ length: count }, (_, index) => ({ id: `dimension-${index}`, name: `实践能力${index + 1}`, description: "科研课程或实践的可观察行为",
    weight: (Math.floor(10000 / count) + (index === 0 ? 10000 % count : 0)) / 10000,
    bars: [1, 2, 3, 4, 5].map((level) => ({ level: level as 1 | 2 | 3 | 4 | 5, anchor: `等级${level}的可观察行为` })) }));
}
const verification: GraduateVerification = { policyVersion: GRADUATE_POLICY_VERSION, cet4Score: 425, cet4Reference: "已查看成绩报告",
  failedGraduateCourses: 0, transcriptReference: "已查看完整研究生成绩单及重修记录", note: "按本岗位标准核验", reviewerId: "recruiter", reviewerName: "招聘者", reviewedAt: "2026-11-03T00:00:00.000Z" };
describe("研究生校招计划与独立硬指标", () => {
  it.each([4, 5, 6].flatMap((count) => [15, 30, 45].map((minutes) => ({ count, minutes }))))("$count维/$minutes分钟包含全部必问，时间预算95%且每维两道评分题", ({ count, minutes }) => {
    const dims = dimensions(count), plan = buildGraduatePlan(dims, minutes);
    expect(plan).toHaveLength(count * 2 + 5); expect(plan.filter((q) => q.mandatory)).toHaveLength(9);
    expect(plan.reduce((sum, row) => sum + row.timeBudgetSec, 0)).toBe(minutes * 60 * .95);
    for (const dim of dims) expect(plan.filter((q) => q.competencyId === dim.id && q.assessmentMode === "scored")).toHaveLength(2);
    for (const question of plan) {
      expect(question.timeBudgetSec).toBeGreaterThan(0); expect(() => assertSafeQuestion(question.prompt)).not.toThrow();
      expect(question.followups).toHaveLength(question.assessmentMode === "scored" ? 2 : 0);
      for (const followup of question.followups) expect(() => assertSafeQuestion(followup.prompt)).not.toThrow();
    }
    expect(graduatePlanVersion(dims, minutes)).toContain(GRADUATE_POLICY_VERSION);
  });
  it("保留原表可见编号，不补造2/4；家庭情况改成自愿工作安排，薪资与资格不作能力评分", () => {
    expect(GRADUATE_TOPICS.filter((row) => row.sourceNumber).map((row) => row.sourceNumber)).toEqual([1, 3, 5, 6, 7, 8, 9]);
    expect(GRADUATE_TOPICS.find((row) => row.key === "compensation")).toMatchObject({ mode: "information" });
    expect(GRADUATE_TOPICS.find((row) => row.key === "work_arrangements")?.prompt).toContain("可以不回答");
    expect(GRADUATE_TOPICS.map((row) => row.prompt).join("")).not.toMatch(/家庭|婚姻|亲属|父母|孩子|年龄|性别|院校/);
    expect(GRADUATE_TOPICS.find((row) => row.key === "graduate_courses")?.prompt).toContain("重修后已通过");
    for (const text of ["请介绍你的家庭情况", "父母从事什么工作", "家庭收入与子女", "婚姻状态"]) expect(() => assertSafeQuestion(text)).toThrow();
  });
  it("能力时间跟随已确认权重，极小正权重仍有正预算，拒绝无效权重", () => {
    const dims = dimensions(4); dims.forEach((dim, index) => { dim.weight = [0.6, 0.2, 0.1999, 0.0001][index]!; });
    const plan = buildGraduatePlan(dims, 15), budget = (id: string) => plan.filter((q) => q.assessmentMode === "scored" && q.competencyId === id).reduce((sum, q) => sum + q.timeBudgetSec, 0);
    expect(budget(dims[0]!.id)).toBeGreaterThan(budget(dims[1]!.id)); expect(plan.every((q) => q.timeBudgetSec > 0)).toBe(true);
    expect(plan.reduce((sum, q) => sum + q.timeBudgetSec, 0)).toBe(855);
    dims[0]!.weight = -1; expect(() => buildGraduatePlan(dims, 15)).toThrow();
  });
  it.each([1, 2, 3, 6, 9])("第%i题是非评分事实题，不作STAR追问", (seq) => {
    const plan = buildGraduatePlan(dimensions(4), 15);
    const result = decideNextAction({ questions: plan, position: { questionSeq: seq, followupsAsked: 0, lastAnswer: "暂时无法提供" }, remainingSec: 800, totalSec: 900 });
    expect(result).toMatchObject({ kind: "ask_question", seq: seq + 1, followupDepth: 0 });
  });
  it("不足20%时优先触达剩余必问并停止追问，耗尽则诚实结束", () => {
    const questions = buildGraduatePlan(dimensions(4), 15), position = { questionSeq: 4, followupsAsked: 0, lastAnswer: "不知道" };
    expect(decideNextAction({ questions, position, remainingSec: 100, totalSec: 900 })).toMatchObject({ kind: "ask_question", seq: 5 });
    expect(decideNextAction({ questions, position: { ...position, questionSeq: 9 }, remainingSec: 100, totalSec: 900 }).kind).toBe("complete");
    expect(decideNextAction({ questions, position, remainingSec: 0, totalSec: 900 }).kind).toBe("complete");
  });
  it("425达标，424或曾挂科1门不达标，未知保持待核验", () => {
    expect(graduateEligibility(verification).status).toBe("met");
    expect(graduateEligibility({ ...verification, cet4Score: 424 }).status).toBe("not_met");
    expect(graduateEligibility({ ...verification, failedGraduateCourses: 1 }).status).toBe("not_met");
    expect(graduateEligibility({ ...verification, failedGraduateCourses: null }).status).toBe("pending");
    expect(graduateEligibility({ ...verification, cet4Reference: "" }).status).toBe("pending");
    expect(graduateEligibility(null).status).toBe("pending");
  });
  it("数值必须有证明来源，不能从客户端伪造核验人或门槛", () => {
    const body = { expectedRevision: 1, cet4Score: 425, cet4Reference: "查看成绩报告", failedGraduateCourses: 0, transcriptReference: "查看完整成绩单", note: "核对原始记录" };
    expect(graduateVerificationInputSchema.safeParse(body).success).toBe(true);
    for (const extra of [{ reviewerId: "forged" }, { cet4Minimum: 400 }, { cet4Score: 711 }, { cet4Reference: "" }, { failedGraduateCourses: -1 }]) expect(graduateVerificationInputSchema.safeParse({ ...body, ...extra }).success).toBe(false);
    expect(graduateVerificationInputSchema.safeParse({ ...body, cet4Score: null, failedGraduateCourses: null, cet4Reference: "", transcriptReference: "" }).success).toBe(true);
  });
  it("覆盖只认真实面试官发言，跳过不伪装回答且未知不当0", () => {
    const questions = [{ id: "q1", topicKey: "introduction", status: "skipped" }, { id: "q2", topicKey: "cet4", status: "pending" }];
    const coverage = graduateCoverage(questions, [{ questionId: "q1", role: "interviewer" }], null);
    expect(coverage).toMatchObject({ status: "pending", mandatoryAsked: 1, mandatoryAnswered: 0, mandatoryTotal: 9, verification: null });
    expect(coverage.topics[0]).toMatchObject({ skipped: true, asked: true, answered: false });
  });
  it("文本与语音同意均包含校招标准，旧版不同意文案不冒充校招同意", () => {
    for (const mode of ["text", "voice"] as const) {
      const consent = consentForMedia({ mode, cameraRequired: false, recruitmentTrack: "graduate_campus" });
      expect(consent.version).toContain("graduate-v1"); expect(consent.text).toContain("425"); expect(consent.text).toContain("重修");
      expect(consent.version).not.toBe(consentForMedia({ mode, cameraRequired: false }).version);
    }
  });
  it("资格更正仅重开人类复核，不重开候选人回答", () => {
    expect(statusAfterQualificationAmendment("reviewed")).toBe("report_ready");
    expect(statusAfterQualificationAmendment("report_ready")).toBe("report_ready");
    expect(() => statusAfterQualificationAmendment("interviewing")).toThrow();
  });
});
