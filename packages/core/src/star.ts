import type { FollowupTrigger } from "./schemas";
import { MAX_FOLLOWUP_DEPTH } from "./budget";

/**
 * STAR 缺项判定。
 *
 * 只在这三种缺项时追问（规格要求）：量化结果 / 个人贡献 / 冲突处理。
 * 用确定性启发式而不是让模型自由决定 —— 追问次数是成本与体验的关键闸门，
 * 不能因为模型「觉得还能再问」就把 15 分钟的面试拖成 30 分钟。
 * M3 引入 LLM 复核时，只允许它「否定」启发式的追问，不允许凭空增加。
 */

export interface StarAnalysis {
  readonly quantified: boolean;
  readonly personalContribution: boolean;
  /** 问题本身是否在问冲突/协作 —— 不是在问，就不判这一项。 */
  readonly conflictRelevant: boolean;
  readonly conflictHandled: boolean;
  readonly gaps: readonly FollowupTrigger[];
}

const QUANTIFIED_PATTERN =
  /(\d+(\.\d+)?\s*(%|％|倍|万|千|百|人|天|小时|分钟|秒|ms|s|元|个|次|家|条|台|单|个百分点))|(\d+(\.\d+)?%)|(百分之[一二三四五六七八九十百\d]+)|((?:为|是|达到|降至|升至|降到|升到|减少到|增加到)\s*\d+)/;
const PERSONAL_PATTERN = /(我(?!们))|本人|自己/;
const CONFLICT_INTENT_PATTERN = /(冲突|分歧|协作|沟通|协调|说服|推动|配合)/;
const CONFLICT_ANSWER_PATTERN = /(冲突|分歧|沟通|协调|妥协|让步|说服|对齐|达成一致|各退一步|取舍)/;
/** 明显敷衍/记不清的回答，直接判为「缺量化结果」并优先追问。 */
const VAGUE_PATTERN = /(记不清|不太记得|大概吧|没什么|忘了|不清楚)/;

export function analyseStarAnswer(answer: string, questionIntent = ""): StarAnalysis {
  const text = answer.trim();
  const quantified = QUANTIFIED_PATTERN.test(text) && !VAGUE_PATTERN.test(text);
  const personalContribution = PERSONAL_PATTERN.test(text);
  // 只由「问题意图」决定是否考察冲突处理：候选人答案里出现「配合」不代表这道题在问冲突，
  // 否则「团队 6 人配合」这种正常表述会被误判成缺项，白白多问一轮。
  const conflictRelevant = CONFLICT_INTENT_PATTERN.test(questionIntent);
  const conflictHandled = conflictRelevant ? CONFLICT_ANSWER_PATTERN.test(text) : true;

  const gaps: FollowupTrigger[] = [];
  if (!quantified) gaps.push("missing_quantified_result");
  if (!personalContribution) gaps.push("missing_personal_contribution");
  if (conflictRelevant && !conflictHandled) gaps.push("missing_conflict_resolution");

  return { quantified, personalContribution, conflictRelevant, conflictHandled, gaps };
}

/**
 * 是否追问：仅当有缺项、且追问层数未超过 2 层。
 * 返回 null 表示应当进入下一题。
 */
export function nextFollowupTrigger(
  answer: string,
  questionIntent: string,
  askedFollowups: number,
): FollowupTrigger | null {
  if (askedFollowups >= MAX_FOLLOWUP_DEPTH) return null;
  const analysis = analyseStarAnswer(answer, questionIntent);
  return analysis.gaps[0] ?? null;
}
