import { z } from "zod";

/**
 * 领域 Zod schema。DB schema、API 契约、LLM 结构化输出三处共用同一套定义，
 * 避免「表里一个样、接口一个样、模型输出又一个样」。
 */

export const JOB_STATUSES = ["draft", "active", "archived"] as const;
export const jobStatusSchema = z.enum(JOB_STATUSES);
export type JobStatus = z.infer<typeof jobStatusSchema>;
export const recruitmentTrackSchema = z.enum(["general", "graduate_campus"]);
export type RecruitmentTrack = z.infer<typeof recruitmentTrackSchema>;

export const INTERVIEW_STATES = [
  "created",
  "invited",
  "consented",
  "warmup",
  "interviewing",
  "wrapping_up",
  "scoring",
  "report_ready",
  "reviewed",
  // 规格扩展：撤回同意 / 招聘者取消，必须有终止态，否则「任意状态可持久化与恢复」无法收尾。
  "cancelled",
] as const;
export const interviewStatusSchema = z.enum(INTERVIEW_STATES);
export type InterviewStatus = z.infer<typeof interviewStatusSchema>;

export const TURN_ROLES = ["interviewer", "candidate", "system"] as const;
export const turnRoleSchema = z.enum(TURN_ROLES);
export type TurnRole = z.infer<typeof turnRoleSchema>;

export const QUESTION_STATUSES = ["pending", "asked", "answered", "skipped"] as const;
export const questionStatusSchema = z.enum(QUESTION_STATUSES);
export type QuestionStatus = z.infer<typeof questionStatusSchema>;

export const COMPETENCY_STATUSES = ["proposed", "confirmed"] as const;
export const competencyStatusSchema = z.enum(COMPETENCY_STATUSES);
export type CompetencyStatus = z.infer<typeof competencyStatusSchema>;

/**
 * 维度分：1–5，或 insufficient_evidence。
 * 用字符串枚举承载 insufficient_evidence，DB 里也存 text，避免 0 分与「无证据」混淆。
 */
export const SCORE_VALUES = ["1", "2", "3", "4", "5", "insufficient_evidence"] as const;
export const scoreValueSchema = z.enum(SCORE_VALUES);
export type ScoreValue = z.infer<typeof scoreValueSchema>;

export const RECOMMENDATIONS = ["strong_yes", "yes", "mixed", "no"] as const;
export const recommendationSchema = z.enum(RECOMMENDATIONS);
export type Recommendation = z.infer<typeof recommendationSchema>;

/** BARS：5 级行为锚点，每级一句可观察的行为描述。 */
export const barsAnchorSchema = z.object({
  level: z.number().int().min(1).max(5),
  anchor: z.string().min(1).max(500),
});
export type BarsAnchor = z.infer<typeof barsAnchorSchema>;

export const barsSchema = z
  .array(barsAnchorSchema)
  .length(5, "BARS 必须正好 5 级")
  .refine(
    (anchors) => new Set(anchors.map((a) => a.level)).size === 5,
    "BARS 的 level 必须互不相同且覆盖 1–5",
  );

export const competencyDraftSchema = z.object({
  name: z.string().min(1).max(60),
  description: z.string().min(1).max(1000),
  weight: z.number().min(0).max(1),
  bars: barsSchema,
});
export type CompetencyDraft = z.infer<typeof competencyDraftSchema>;

export const WEIGHT_SUM_TOLERANCE = 0.01;

export const competencySetSchema = z
  .object({
    competencies: z.array(competencyDraftSchema).min(4).max(6),
  })
  .refine((set) => new Set(set.competencies.map((c) => c.name)).size === set.competencies.length, {
    message: "维度名不能重复",
    path: ["competencies"],
  })
  .refine(
    (set) => Math.abs(set.competencies.reduce((sum, c) => sum + c.weight, 0) - 1) <= WEIGHT_SUM_TOLERANCE,
    { message: `维度权重之和必须为 1（容差 ${WEIGHT_SUM_TOLERANCE}）`, path: ["competencies"] },
  );
export type CompetencySet = z.infer<typeof competencySetSchema>;

/** 简历结构化档案：只保留与胜任力评估相关的信息，受保护属性在解析阶段即被剔除。 */
export const resumeExperienceSchema = z.object({
  company: z.string(),
  title: z.string(),
  start: z.string().nullable(),
  end: z.string().nullable(),
  highlights: z.array(z.string()),
});
export type ResumeExperience = z.infer<typeof resumeExperienceSchema>;

export const resumeProfileSchema = z.object({
  summary: z.string().default(""),
  experiences: z.array(resumeExperienceSchema).default([]),
  skills: z.array(z.string()).default([]),
  projects: z.array(z.object({ name: z.string(), detail: z.string() })).default([]),
  achievements: z.array(z.string()).default([]),
});
export type ResumeProfile = z.infer<typeof resumeProfileSchema>;

/** 「待验证声明」：简历里的量化/主导类断言，进面试时必须被追问验证。 */
export const unverifiedClaimSchema = z.object({
  id: z.string(),
  text: z.string().min(1),
  sourceSection: z.string().min(1),
  relatedCompetencyHint: z.string().nullable().default(null),
});
export type UnverifiedClaim = z.infer<typeof unverifiedClaimSchema>;

/**
 * 追问树节点：只在 STAR 缺项（量化结果 / 个人贡献 / 冲突处理）时触发，最多 2 层。
 */
export const FOLLOWUP_TRIGGERS = [
  "missing_quantified_result",
  "missing_personal_contribution",
  "missing_conflict_resolution",
] as const;
export const followupTriggerSchema = z.enum(FOLLOWUP_TRIGGERS);
export type FollowupTrigger = z.infer<typeof followupTriggerSchema>;

export const followupNodeSchema = z.object({
  depth: z.union([z.literal(1), z.literal(2)]),
  trigger: followupTriggerSchema,
  prompt: z.string().min(1).max(500),
});
export type FollowupNode = z.infer<typeof followupNodeSchema>;

/** 报告里每个维度的汇总行（证据 id 列表必须非空，除非分数为 insufficient_evidence）。 */
export const reportDimensionScoreSchema = z.object({
  competencyId: z.string(),
  competencyName: z.string(),
  weight: z.number().min(0).max(1),
  score: scoreValueSchema,
  needsReview: z.boolean(),
  evidenceIds: z.array(z.string()),
  sampleValues: z.array(scoreValueSchema).max(2).optional(),
  rationale: z.string().optional(),
}).refine(
  (row) => row.score === "insufficient_evidence" ? row.evidenceIds.length === 0 : row.evidenceIds.length > 0,
  { message: "数值评分必须引用证据；证据不足时不得伪造引用", path: ["evidenceIds"] },
);
export type ReportDimensionScore = z.infer<typeof reportDimensionScoreSchema>;

/** 报告元数据：token 数与估算成本（验收要求）。 */
export const reportMetadataSchema = z.object({
  provider: z.string(),
  model: z.string(),
  promptTokens: z.number().int().nonnegative(),
  completionTokens: z.number().int().nonnegative(),
  totalTokens: z.number().int().nonnegative(),
  estimatedCostUsd: z.number().nonnegative(),
  generatedAt: z.string().datetime(),
  transcriptRedacted: z.boolean(),
  samplingRuns: z.number().int().min(1).max(2),
  costBasis: z.enum(["fixture_free", "configured_rates", "unpriced_internal"]).optional(),
  usageEstimated: z.boolean().optional(),
  transcriptHash: z.string().optional(),
}).refine((row) => row.totalTokens === row.promptTokens + row.completionTokens, {
  message: "totalTokens 必须等于输入与输出 token 之和", path: ["totalTokens"],
});
export type ReportMetadata = z.infer<typeof reportMetadataSchema>;

/** 面试计划：LLM 产出的题目草稿（时间预算由系统分配，不采信模型给的值）。 */
export const plannedQuestionDraftSchema = z.object({
  competencyName: z.string().min(1),
  prompt: z.string().min(10).max(600),
  intent: z.string().min(2).max(200),
  followups: z.array(followupNodeSchema).max(2).default([]),
});
export type PlannedQuestionDraft = z.infer<typeof plannedQuestionDraftSchema>;

export const questionPlanSchema = z.object({
  questions: z.array(plannedQuestionDraftSchema).min(4).max(24),
});
export type QuestionPlan = z.infer<typeof questionPlanSchema>;

export const consentSchema = z.object({
  consentVersion: z.string().min(1),
  consentTextHash: z.string().min(1),
  recordingAllowed: z.boolean(),
  consentedAt: z.date(),
});
export type Consent = z.infer<typeof consentSchema>;

export const apiErrorSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.unknown().optional(),
  }),
});
export type ApiError = z.infer<typeof apiErrorSchema>;

/**
 * 受保护属性：不得询问、不得推断、不得写入简历档案。
 * 名单同时用于解析层剔除与测试断言（受保护属性相关提问数必须为 0）。
 */
export const PROTECTED_ATTRIBUTES = [
  "age",
  "birthDate",
  "dateOfBirth",
  "gender",
  "sex",
  "maritalStatus",
  "children",
  "pregnancy",
  "ethnicity",
  "race",
  "religion",
  "health",
  "disability",
  "politicalAffiliation",
  "sexualOrientation",
  "hukou",
  "householdRegistration",
  "nationality",
  "photo",
  "idCardNumber",
] as const;
export type ProtectedAttribute = (typeof PROTECTED_ATTRIBUTES)[number];

const PROTECTED_ATTRIBUTE_SET: ReadonlySet<string> = new Set(PROTECTED_ATTRIBUTES);

export function isProtectedAttribute(key: string): boolean {
  return PROTECTED_ATTRIBUTE_SET.has(key);
}
