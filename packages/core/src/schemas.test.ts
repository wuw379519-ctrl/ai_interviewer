import { describe, expect, it } from "vitest";
import {
  barsSchema,
  PROTECTED_ATTRIBUTES,
  reportDimensionScoreSchema,
  reportMetadataSchema,
} from "./schemas";
import { redactText, sanitizeResumeProfile } from "./redact";

describe("领域契约", () => {
  it("BARS 拒绝重复等级", () => {
    expect(barsSchema.safeParse(Array.from({ length: 5 }, () => ({ level: 1, anchor: "重复" }))).success).toBe(false);
  });

  it.each([
    ["4", []],
    ["insufficient_evidence", ["invented"]],
  ])("报告分数 %s 拒绝非法证据集合", (score, evidenceIds) => {
    expect(reportDimensionScoreSchema.safeParse({
      competencyId: "c1", competencyName: "工程实现", weight: 0.25,
      score, needsReview: false, evidenceIds,
    }).success).toBe(false);
  });

  it("报告 token 总数必须可核对", () => {
    expect(reportMetadataSchema.safeParse({
      provider: "fake", model: "fixture", promptTokens: 10, completionTokens: 2,
      totalTokens: 100, estimatedCostUsd: 0, generatedAt: "2026-11-02T00:00:00.000Z",
      transcriptRedacted: true, samplingRuns: 1,
    }).success).toBe(false);
  });
});

describe("简历白名单与去标识化", () => {
  it("剔除所有受保护字段和嵌套字段，保留岗位经历", () => {
    const protectedFields = Object.fromEntries(PROTECTED_ATTRIBUTES.map((key) => [key, "不应保留"]));
    const result = sanitizeResumeProfile({
      ...protectedFields,
      summary: "我叫测试候选人，年龄：32，性别：女，宗教：佛教，性取向：双性恋，主导 DAU 提升 30%。",
      experiences: [{
        ...protectedFields, company: "示例科技", title: "工程师", start: "2021-03", end: null,
        highlights: ["户籍：上海，政治面貌：党员，完成系统重构，延迟降低 40%。"],
      }],
      projects: [{ name: "性能优化", detail: "健康状况：良好，邮箱 a@example.com，首屏降低 2 秒。", religion: "不保留" }],
    }, { candidateName: "测试候选人" });
    const serialized = JSON.stringify(result);
    for (const key of PROTECTED_ATTRIBUTES) {
      expect(result).not.toHaveProperty(key);
      expect(result.experiences[0]).not.toHaveProperty(key);
    }
    for (const term of ["测试候选人", "32", "佛教", "双性恋", "上海", "党员", "良好", "a@example.com"]) {
      expect(serialized).not.toContain(term);
    }
    expect(result.summary).toContain("DAU 提升 30%");
    expect(result.experiences[0]?.highlights[0]).toContain("延迟降低 40%");
    expect(result.experiences[0]?.start).toBe("2021-03");
    expect(result.projects[0]?.detail).toContain("首屏降低 2 秒");
  });

  it.each([
    "男，已婚已育，信仰基督教，同性恋",
    "Age: 32; gender: female; religion: Buddhism; sexual orientation: bisexual",
    "32 years old, male",
  ])("处理显式受保护属性：%s", (text) => {
    const result = redactText(text).text;
    expect(result).not.toMatch(/已婚|已育|基督教|同性恋|\b32\b|\bfemale\b|\bmale\b|Buddhism|bisexual/);
  });

  it("脱敏手机号、邮箱、身份证，不改写项目量化结果", () => {
    const result = redactText("13800138000 / a@example.com / 110101199003071234；提升 30%，团队 6 人").text;
    expect(result).not.toMatch(/13800138000|a@example.com|110101199003071234/);
    expect(result).toContain("提升 30%");
    expect(result).toContain("团队 6 人");
  });
});
