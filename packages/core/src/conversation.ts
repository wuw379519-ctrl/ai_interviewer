import { MAX_FOLLOWUP_DEPTH, shouldWrapUp } from "./budget";
import { nextFollowupTrigger } from "./star";
import type { FollowupNode, FollowupTrigger } from "./schemas";

/**
 * 对话推进：纯函数，不碰数据库、不调模型。
 *
 * 面试中每一次「下一句说什么」都在这里决定，好处是可测试、可重放：
 * 断线恢复时把 turns 重新喂进来，得到的下一步与断线前完全一致。
 */

export interface PlanQuestionLike {
  mandatory?: boolean;
  assessmentMode?: "scored" | "information" | "eligibility";
  seq: number;
  prompt: string;
  intent: string;
  followups: readonly FollowupNode[];
  timeBudgetSec: number;
}

export type AskAction =
  | { kind: "ask_question"; seq: number; text: string; followupDepth: 0 }
  | { kind: "ask_followup"; seq: number; text: string; followupDepth: 1 | 2; trigger: FollowupTrigger }
  | { kind: "wrap_up"; text: string; followupDepth: 0 }
  | { kind: "complete"; text: string; followupDepth: 0 };

export const WRAP_UP_TEXT = "时间差不多了，我们先收一下尾：这题你还有什么要补充的关键结果吗？";
export const COMPLETE_TEXT = "本次面试到此结束，谢谢你的时间。评估报告会由招聘者复核后再与你沟通下一步。";

const FALLBACK_FOLLOWUPS: Readonly<Record<FollowupTrigger, string>> = {
  missing_quantified_result: "这件事最后有量化的结果吗？比如具体数字、比例，或者前后变化了多少。",
  missing_personal_contribution: "这里面哪些部分是你亲自做的？团队里其他人分别负责什么？",
  missing_conflict_resolution: "当时的分歧具体卡在哪里？你做了什么让对方接受这个方案？",
};

export interface ConversationPosition {
  /** 当前问到的题号，0 表示还没开始。 */
  questionSeq: number;
  /** 当前题已发出的追问次数。 */
  followupsAsked: number;
  /** 当前题最近最多三段候选人回答，用于判断 STAR 尚缺哪些信息。 */
  lastAnswer?: string;
}

export interface DecideInput {
  questions: readonly PlanQuestionLike[];
  position: ConversationPosition;
  remainingSec: number;
  totalSec: number;
}

export function decideNextAction(input: DecideInput): AskAction {
  const ordered = [...input.questions].sort((a, b) => a.seq - b.seq);
  if (ordered.length === 0) {
    return { kind: "complete", text: COMPLETE_TEXT, followupDepth: 0 };
  }

  // 剩余时间不足 20%：不再开新题，进入收敛收尾
  if (shouldWrapUp(input.remainingSec, input.totalSec)) {
    if (ordered.some((question) => question.mandatory)) {
      const pending = ordered.find((question) => question.mandatory && question.seq > input.position.questionSeq);
      if (pending && input.remainingSec > 0) return { kind: "ask_question", seq: pending.seq, text: pending.prompt, followupDepth: 0 };
      return { kind: "complete", text: COMPLETE_TEXT, followupDepth: 0 };
    }
    const current = ordered.find((question) => question.seq === input.position.questionSeq);
    return { kind: "wrap_up", text: current ? WRAP_UP_TEXT : COMPLETE_TEXT, followupDepth: 0 };
  }

  if (input.position.questionSeq === 0) {
    const first = ordered[0]!;
    return { kind: "ask_question", seq: first.seq, text: first.prompt, followupDepth: 0 };
  }

  const current = ordered.find((question) => question.seq === input.position.questionSeq);
  if (!current) {
    return { kind: "complete", text: COMPLETE_TEXT, followupDepth: 0 };
  }

  if (input.position.lastAnswer !== undefined) {
    const followupsAsked = input.position.followupsAsked;
    if (followupsAsked < MAX_FOLLOWUP_DEPTH && (!current.assessmentMode || current.assessmentMode === "scored")) {
      const trigger = nextFollowupTrigger(input.position.lastAnswer, current.intent, followupsAsked);
      if (trigger) {
        const depth = (followupsAsked + 1) as 1 | 2;
        const planned = current.followups.find((node) => node.trigger === trigger && node.depth === depth);
        return {
          kind: "ask_followup",
          seq: current.seq,
          text: planned?.prompt ?? FALLBACK_FOLLOWUPS[trigger],
          followupDepth: depth,
          trigger,
        };
      }
    }

    const next = ordered.find((question) => question.seq === current.seq + 1);
    if (next) {
      return { kind: "ask_question", seq: next.seq, text: next.prompt, followupDepth: 0 };
    }
    return { kind: "complete", text: COMPLETE_TEXT, followupDepth: 0 };
  }

  // 没有新回答（例如候选人点了「重复」）：原题重发
  return { kind: "ask_question", seq: current.seq, text: current.prompt, followupDepth: 0 };
}

export interface TurnLike {
  questionId: string | null;
  role: string;
  isFollowup: boolean;
  content: string;
}

export interface DerivedState extends ConversationPosition {
  pendingQuestionId: string | null;
  answeredQuestionSeqs: number[];
}

/**
 * 从持久化的 turns 反推「当前在哪一题、追问到第几层」。
 * 断线 30 秒后重连时以服务端 turns 为准，客户端不需要（也不允许）自己记进度。
 */
export function deriveConversationState(
  questions: readonly (PlanQuestionLike & { id: string })[],
  turns: readonly TurnLike[],
): DerivedState {
  const ordered = [...questions].sort((a, b) => a.seq - b.seq);

  let currentSeq = 0;
  for (const turn of turns) {
    const question = ordered.find((item) => item.id === turn.questionId);
    if (question && question.seq > currentSeq) currentSeq = question.seq;
  }

  if (currentSeq === 0) {
    return { questionSeq: 0, followupsAsked: 0, pendingQuestionId: null, answeredQuestionSeqs: [] };
  }

  const current = ordered.find((question) => question.seq === currentSeq);
  const currentTurns = turns.filter((turn) => turn.questionId === current?.id);
  const candidateTurns = currentTurns.filter((turn) => turn.role === "candidate");
  const recentAnswers = candidateTurns.slice(-3).map((turn) => turn.content).join("\n");

  const answeredQuestionSeqs = ordered
    .filter((question) => turns.some((turn) => turn.questionId === question.id && turn.role === "candidate"))
    .map((question) => question.seq);

  return {
    questionSeq: currentSeq,
    followupsAsked: currentTurns.filter((turn) => turn.role === "interviewer" && turn.isFollowup).length,
    ...(recentAnswers ? { lastAnswer: recentAnswers } : {}),
    pendingQuestionId: current?.id ?? null,
    answeredQuestionSeqs,
  };
}

/** 候选人可请求重复（不计入追问层数）或跳过（直接下一题）。 */
export const CANDIDATE_ACTIONS = ["answer", "repeat", "skip"] as const;
export type CandidateAction = (typeof CANDIDATE_ACTIONS)[number];
