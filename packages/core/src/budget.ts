import { DomainError } from "./errors";

/**
 * 时长预算分配。
 *
 * 所有档位每维度至少 2 题、最多 3 题（4–6 维度，总计 8–18 题）。
 * 15 分钟缩短每题预算，不减少核心题；追问占用本题预算。
 * 「提问单元」= 一次主问题；追问从该题预算里扣，不额外加时。
 */

export const DURATION_TIERS = [15, 30, 45] as const;
export type DurationTier = (typeof DURATION_TIERS)[number];

export interface TierProfile {
  readonly tier: DurationTier;
  readonly minUnits: number;
  readonly maxUnits: number;
  readonly maxPerDimension: number;
}

export const TIER_PROFILES: Readonly<Record<DurationTier, TierProfile>> = {
  15: { tier: 15, minUnits: 8, maxUnits: 12, maxPerDimension: 2 },
  30: { tier: 30, minUnits: 8, maxUnits: 18, maxPerDimension: 3 },
  45: { tier: 45, minUnits: 8, maxUnits: 18, maxPerDimension: 3 },
};

/** 计划占用配置时长的 95%，留 5% 给开场白与收尾，保证总时长落在 ±10% 内。 */
export const PLANNED_TIME_RATIO = 0.95;
/** 运行期剩余时间低于 20% 即进入收敛收尾。 */
export const WRAP_UP_REMAINING_RATIO = 0.2;
/** 验收要求的时长误差上限。 */
export const DURATION_TOLERANCE = 0.1;
/** 追问最多 2 层。 */
export const MAX_FOLLOWUP_DEPTH = 2;

const TARGET_SECONDS_PER_UNIT = 180;

export function resolveTier(durationMinutes: number): DurationTier {
  if ((DURATION_TIERS as readonly number[]).includes(durationMinutes)) {
    return durationMinutes as DurationTier;
  }
  throw new DomainError("VALIDATION_FAILED", `仅支持 15 / 30 / 45 分钟三档，收到 ${durationMinutes}`, {
    durationMinutes,
  });
}

export interface PlanAllocation {
  readonly tier: TierProfile;
  /** 计划占用的总秒数（应落在 durationMinutes*60 的 ±10% 内）。 */
  readonly plannedSec: number;
  readonly totalUnits: number;
  /** 每个维度分配到的提问单元数，顺序与传入权重一致。 */
  readonly perDimension: number[];
  /** 每个提问单元的时间预算（秒），总和 === plannedSec。 */
  readonly questionSeconds: number[];
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * 维度 × 时长 → 每维度题数 + 每题预算。
 * 规则：先保证每个维度 2 题，再按权重从高到低分配第 3 题。
 */
export function allocatePlan(durationMinutes: number, weights: readonly number[]): PlanAllocation {
  const tier = TIER_PROFILES[resolveTier(durationMinutes)];

  if (weights.length < 4 || weights.length > 6) {
    throw new DomainError("VALIDATION_FAILED", `维度数必须在 4–6 之间，收到 ${weights.length}`, {
      competencyCount: weights.length,
    });
  }
  if (weights.some((weight) => !Number.isFinite(weight) || weight <= 0) ||
      weights.reduce((sum, weight) => sum + Math.round(weight * 10000), 0) !== 10000) {
    throw new DomainError("COMPETENCY_WEIGHT_SUM_INVALID", "维度权重必须为正，万分比之和必须为 10000");
  }

  const plannedSec = Math.round(durationMinutes * 60 * PLANNED_TIME_RATIO);
  const lower = Math.max(tier.minUnits, weights.length * 2);
  const upper = Math.min(tier.maxUnits, weights.length * tier.maxPerDimension);
  const target = clamp(Math.round(plannedSec / TARGET_SECONDS_PER_UNIT), lower, upper);

  const perDimension: number[] = weights.map(() => 2);
  const order = weights
    .map((weight, index) => ({ index, weight }))
    .sort((a, b) => b.weight - a.weight || a.index - b.index)
    .map((entry) => entry.index);

  let remaining = target - perDimension.reduce((sum, count) => sum + count, 0);
  let cursor = 0;
  while (remaining > 0) {
    const index = order[cursor % order.length]!;
    if (perDimension[index]! < tier.maxPerDimension) {
      perDimension[index]! += 1;
      remaining -= 1;
    } else if (perDimension.every((count) => count >= tier.maxPerDimension)) {
      break;
    }
    cursor += 1;
    if (cursor > target * order.length + order.length) break;
  }

  const totalUnits = perDimension.reduce((sum, count) => sum + count, 0);
  const base = Math.floor(plannedSec / totalUnits);
  const remainder = plannedSec - base * totalUnits;
  const questionSeconds: number[] = [];
  for (let index = 0; index < totalUnits; index += 1) {
    questionSeconds.push(base + (index < remainder ? 1 : 0));
  }

  return { tier, plannedSec, totalUnits, perDimension, questionSeconds };
}

export interface ToleranceCheck {
  /** 计划时长 / 配置时长 - 1，负数表示比配置短。 */
  readonly deviation: number;
  readonly withinTolerance: boolean;
}

export function planTolerance(plannedSec: number, durationMinutes: number): ToleranceCheck {
  const configured = durationMinutes * 60;
  const deviation = plannedSec / configured - 1;
  return { deviation, withinTolerance: Math.abs(deviation) <= DURATION_TOLERANCE };
}

export function remainingRatio(remainingSec: number, totalSec: number): number {
  if (totalSec <= 0) return 0;
  return clamp(remainingSec / totalSec, 0, 1);
}

/** 剩余时间不足 20% → 收敛收尾（不再开新题，只做收尾与追问最后一句）。 */
export function shouldWrapUp(remainingSec: number, totalSec: number): boolean {
  return remainingRatio(remainingSec, totalSec) < WRAP_UP_REMAINING_RATIO;
}
