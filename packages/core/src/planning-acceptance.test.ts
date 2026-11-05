import { describe, expect, it } from "vitest";
import { allocatePlan } from "./budget";
import { assertSafeQuestion } from "./intake";
import { decideNextAction } from "./conversation";

describe("M2 题量与时长验收", () => {
  for (const count of [4, 5, 6]) {
    for (const duration of [15, 30, 45]) {
      it(`${duration} 分钟 × ${count} 维度，至少 8 题且每维度 2–3 题`, () => {
        const weights = Array.from({ length: count }, (_, index) => (Math.floor(10000 / count) + (index < 10000 % count ? 1 : 0)) / 10000);
        const plan = allocatePlan(duration, weights);
        expect(plan.totalUnits).toBeGreaterThanOrEqual(8);
        expect(plan.perDimension.every((number) => number >= 2 && number <= 3)).toBe(true);
        expect(plan.questionSeconds.reduce((sum, seconds) => sum + seconds, 0)).toBe(plan.plannedSec);
        expect(Math.abs(plan.plannedSec / (duration * 60) - 1)).toBeLessThanOrEqual(0.1);
      });
    }
  }
  it.each([[NaN, .25, .25, .25], [-.1, .3, .4, .4], [.1, .1, .1, .1]])("拒绝无效权重 %j", (...weights) => {
    expect(() => allocatePlan(15, weights)).toThrow();
  });
  it("剩余不足 20% 即使有新答案也收尾，不再开新题", () => {
    const result = decideNextAction({ questions: [{ seq: 1, prompt: "请分享你的项目", intent: "验证执行", followups: [], timeBudgetSec: 100 }],
      position: { questionSeq: 1, followupsAsked: 0, lastAnswer: "我负责方案，提升40%" }, remainingSec: 100, totalSec: 900 });
    expect(result.kind).toBe("wrap_up");
  });
  it.each(["你的年龄是多少？", "你的性别是什么？", "你是否有结婚或生育计划？", "你属于什么民族？", "你有什么宗教信仰？", "你的健康状况如何？", "你是否有残障？", "你的政治倾向是什么？", "你的性取向是什么？", "你的户籍在哪里？"])("拒绝受保护属性题目：%s", (question) => {
    expect(() => assertSafeQuestion(question)).toThrow();
  });
});
