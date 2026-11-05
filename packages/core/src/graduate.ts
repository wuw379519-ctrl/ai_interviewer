import { z } from "zod";
import type { PlanCompetency, PlannedQuestion } from "./plan";
import { computePlanVersion } from "./plan";
import { resolveTier, PLANNED_TIME_RATIO } from "./budget";
import { assertSafeQuestion } from "./intake";
import { DomainError } from "./errors";
import type { FollowupNode, InterviewStatus } from "./schemas";

export { recruitmentTrackSchema, type RecruitmentTrack } from "./schemas";
export const GRADUATE_POLICY_VERSION = "graduate-campus-v1-cet425";
export const CET4_MIN_SCORE = 425;
export const GRADUATE_DIMENSIONS = ["研究与实践", "分析与解决问题", "学习与成长", "岗位认知与协作"] as const;
export type AssessmentMode = "scored" | "information" | "eligibility";
export const GRADUATE_TOPICS = [
  { key: "introduction", label: "自我介绍", sourceNumber: 1, mode: "information", dimension: 0, prompt: "请用约1分钟介绍你的研究方向、相关技能，以及一项与你应聘岗位相关的个人工作。" },
  { key: "cet4", label: "英语四级硬指标核验", sourceNumber: null, mode: "eligibility", dimension: 0, prompt: "请说明CET-4总分、考试时间，以及可供招聘者人工核验的成绩报告来源；暂时无法确认可以直接说明。本岗位要求总分至少425分。" },
  { key: "graduate_courses", label: "研究生课程硬指标核验", sourceNumber: null, mode: "eligibility", dimension: 0, prompt: "请说明研究生期间是否曾有课程不及格记录，包含补考或重修后已通过的情况，并说明可供人工核验的完整成绩单来源。本岗位要求研究生期间没有挂科记录。" },
  { key: "project", label: "项目经验", sourceNumber: 3, mode: "scored", dimension: 0, prompt: "请选择一个研究生期间的科研、课程、竞赛或实习项目，说明任务、你的个人贡献、使用的方法与可验证结果。" },
  { key: "motivation", label: "求职动机", sourceNumber: 5, mode: "scored", dimension: 3, prompt: "你为什么选择本岗位？请结合对岗位工作的理解，以及一次能体现岗位匹配的学习或实践经历说明。" },
  { key: "compensation", label: "期望收入", sourceNumber: 6, mode: "information", dimension: 0, prompt: "请按税前人民币说明期望月薪、期望年薪及可接受最低薪资，并说明12薪或13薪等口径；不确定或不愿披露最低值也可以说明。" },
  { key: "career", label: "职业规划", sourceNumber: 7, mode: "scored", dimension: 2, prompt: "未来1至3年你希望发展哪些岗位能力？请结合一次学习或实践经历，说明你为此做过什么以及如何验证进步。" },
  { key: "self_evaluation", label: "自我评价", sourceNumber: 8, mode: "scored", dimension: 1, prompt: "结合岗位要求，请用具体经历说明一项优势和一项待提升能力，以及已经采取的改进行动。" },
  { key: "work_arrangements", label: "工作安排（替代家庭情况，自愿回答）", sourceNumber: 9, mode: "information", dimension: 0, prompt: "关于工作安排，你是否有愿意说明的到岗时间、工作地点或出差安排约束？此项可以不回答，也不需要解释个人原因。" },
] as const;
export function graduatePlanVersion(competencies: readonly PlanCompetency[], minutes: number) {
  return `${GRADUATE_POLICY_VERSION}-questions-v1-${computePlanVersion(competencies, minutes)}`;
}
function graduateFollowups(): FollowupNode[] {
  return [
    { depth: 1, trigger: "missing_quantified_result", prompt: "这个研究或实践最后有哪些可核验结果？可以说明数字、对照情况或前后变化。" },
    { depth: 2, trigger: "missing_personal_contribution", prompt: "在这项工作中，你个人具体负责哪些行动？其他成员分别做了什么？" },
  ];
}
export function buildGraduatePlan(competencies: readonly PlanCompetency[], minutes: number): PlannedQuestion[] {
  resolveTier(minutes);
  if (competencies.length < 4 || competencies.length > 6 || competencies.some((row) => !Number.isFinite(row.weight) || row.weight <= 0) || competencies.reduce((sum, row) => sum + Math.round(row.weight * 10000), 0) !== 10000) throw new DomainError("COMPETENCY_NOT_CONFIRMED", "研究生校招需要4至6个已确认且正权重合计100%的维度");
  const rows: PlannedQuestion[] = GRADUATE_TOPICS.map((topic, index) => ({ seq: index + 1, competencyId: competencies[topic.dimension]!.id,
    competencyName: competencies[topic.dimension]!.name, prompt: topic.prompt, intent: topic.mode === "scored" ? "验证研究生实践中的个人行动与结果" : "收集岗位事实，不作能力评分，不作STAR追问",
    followups: topic.mode === "scored" ? graduateFollowups() : [], timeBudgetSec: 1, topicKey: topic.key, mandatory: true, assessmentMode: topic.mode }));
  for (const competency of competencies) {
    const count = rows.filter((row) => row.competencyId === competency.id && row.assessmentMode === "scored").length;
    for (let index = count; index < 2; index++) rows.push({ seq: rows.length + 1, competencyId: competency.id, competencyName: competency.name,
      prompt: `请再分享一个体现「${competency.name}」的研究、课程、竞赛或实习案例，说明个人行动、关键取舍与可验证结果（补充${index + 1}）。`,
      intent: `验证${competency.name}的个人贡献与结果`, followups: graduateFollowups(), timeBudgetSec: 1, topicKey: null, mandatory: false, assessmentMode: "scored" });
  }
  const units = rows.map((row) => row.assessmentMode === "scored" ? 100 * competencies.length * competencies.find((dim) => dim.id === row.competencyId)!.weight : row.assessmentMode === "eligibility" ? 45 : row.topicKey === "introduction" ? 60 : row.topicKey === "compensation" ? 40 : 25);
  const total = Math.round(minutes * 60 * PLANNED_TIME_RATIO), sum = units.reduce((a, b) => a + b, 0);
  rows.forEach((row, index) => { assertSafeQuestion(row.prompt); row.timeBudgetSec = 1 + Math.floor((total - rows.length) * units[index]! / sum); });
  let remainder = total - rows.reduce((value, row) => value + row.timeBudgetSec, 0);
  for (const row of rows) { if (remainder-- > 0) row.timeBudgetSec++; }
  return rows;
}

export const graduateVerificationInputSchema = z.object({ expectedRevision: z.number().int().positive(),
  cet4Score: z.number().int().min(0).max(710).nullable(), cet4Reference: z.string().trim().max(200),
  failedGraduateCourses: z.number().int().min(0).max(200).nullable(), transcriptReference: z.string().trim().max(200), note: z.string().trim().min(4).max(600),
}).strict().superRefine((row, context) => {
  if (row.cet4Score !== null && row.cet4Reference.length < 3) context.addIssue({ code: z.ZodIssueCode.custom, path: ["cet4Reference"], message: "录入已核验分数必须填写成绩报告核验来源" });
  if (row.failedGraduateCourses !== null && row.transcriptReference.length < 3) context.addIssue({ code: z.ZodIssueCode.custom, path: ["transcriptReference"], message: "录入挂科数必须填写完整研究生成绩单核验来源" });
});
export type GraduateVerificationInput = z.infer<typeof graduateVerificationInputSchema>;
export function statusAfterQualificationAmendment(status: InterviewStatus): "report_ready" {
  if (status !== "report_ready" && status !== "reviewed") throw new DomainError("RESOURCE_CONFLICT", "请先生成校招报告再更正资格核验");
  return "report_ready";
}
export const graduateVerificationSchema = z.object({ cet4Score: z.number().int().min(0).max(710).nullable(), cet4Reference: z.string(),
  failedGraduateCourses: z.number().int().min(0).max(200).nullable(), transcriptReference: z.string(), note: z.string(),
  policyVersion: z.literal(GRADUATE_POLICY_VERSION), reviewerId: z.string(), reviewerName: z.string(), reviewedAt: z.string().datetime() });
export type GraduateVerification = z.infer<typeof graduateVerificationSchema>;
const criterionStatus = z.enum(["met", "not_met", "pending"]);
export const graduateReportSchema = z.object({ policyVersion: z.literal(GRADUATE_POLICY_VERSION), cet4Minimum: z.literal(425),
  status: criterionStatus, cet4Status: criterionStatus, graduateCoursesStatus: criterionStatus,
  verification: graduateVerificationSchema.nullable(), mandatoryAsked: z.number().int(), mandatoryAnswered: z.number().int(), mandatoryTotal: z.number().int(),
  topics: z.array(z.object({ key: z.string(), label: z.string(), sourceNumber: z.number().nullable(), asked: z.boolean(), answered: z.boolean(), skipped: z.boolean(),
    responses: z.array(z.object({ turnId: z.string().uuid(), quote: z.string().max(4000) })).default([]) })),
});
export type GraduateReport = z.infer<typeof graduateReportSchema>;
export function graduateEligibility(verification: GraduateVerification | null) {
  const cet4Status = verification?.cet4Score !== null && verification?.cet4Score !== undefined && verification.cet4Reference.trim().length >= 3
    ? verification.cet4Score >= CET4_MIN_SCORE ? "met" as const : "not_met" as const : "pending" as const;
  const graduateCoursesStatus = verification?.failedGraduateCourses !== null && verification?.failedGraduateCourses !== undefined && verification.transcriptReference.trim().length >= 3
    ? verification.failedGraduateCourses === 0 ? "met" as const : "not_met" as const : "pending" as const;
  const status = cet4Status === "not_met" || graduateCoursesStatus === "not_met" ? "not_met" as const : cet4Status === "met" && graduateCoursesStatus === "met" ? "met" as const : "pending" as const;
  return { status, cet4Status, graduateCoursesStatus };
}
export function graduateCoverage(questions: readonly { id: string; topicKey: string | null; status: string }[], turns: readonly { id?: string; content?: string; questionId: string | null; role: string }[], verification: GraduateVerification | null): GraduateReport {
  const topics = GRADUATE_TOPICS.map((topic) => {
    const question = questions.find((row) => row.topicKey === topic.key);
    return { key: topic.key, label: topic.label, sourceNumber: topic.sourceNumber,
      asked: Boolean(question && turns.some((turn) => turn.questionId === question.id && turn.role === "interviewer")),
      answered: Boolean(question && turns.some((turn) => turn.questionId === question.id && turn.role === "candidate")), skipped: question?.status === "skipped",
      responses: question ? turns.filter((turn) => turn.questionId === question.id && turn.role === "candidate" && turn.id && turn.content).map((turn) => ({ turnId: turn.id!, quote: turn.content! })) : [] };
  });
  return { policyVersion: GRADUATE_POLICY_VERSION, cet4Minimum: CET4_MIN_SCORE, ...graduateEligibility(verification), verification,
    topics, mandatoryAsked: topics.filter((row) => row.asked).length, mandatoryAnswered: topics.filter((row) => row.answered).length, mandatoryTotal: topics.length };
}
