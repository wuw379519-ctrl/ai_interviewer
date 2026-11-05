import { z } from "zod";
import { DomainError } from "./errors";
import { redactText } from "./redact";

export const MAX_RETENTION_DAYS = 90;
export const retentionPolicySchema = z.object({ retentionDays: z.number().int().min(1).max(MAX_RETENTION_DAYS), revision: z.number().int().positive() });
export const updateRetentionSchema = z.object({ retentionDays: retentionPolicySchema.shape.retentionDays, expectedRevision: z.number().int().positive(), reason: z.string().trim().min(4).max(300) }).strict();
export const deleteCandidateSchema = z.object({ confirmCandidateId: z.string().uuid(), reason: z.string().trim().min(4).max(300) }).strict();
export const cleanupInputSchema = z.object({ previewToken: z.string().min(40).max(1000), reason: z.string().trim().min(4).max(300) }).strict();
export const erasureResultSchema = z.object({ candidateId: z.string().uuid(), deleted: z.literal(true), alreadyDeleted: z.boolean(), interviewsErased: z.number().int().nonnegative() });
export const erasurePreviewSchema = z.object({ candidateId: z.string().uuid(), label: z.string(), deleted: z.boolean(), counts: z.object({ interviews: z.number().int(), resumes: z.number().int(), turns: z.number().int(), reports: z.number().int(), scores: z.number().int(), caches: z.number().int() }) });
export const cleanupSelectionSchema = z.object({ cutoffAt: z.string().datetime(), policyRevision: z.number().int().positive(),
  candidateIds: z.array(z.string().uuid()), interviewIds: z.array(z.string().uuid()), cacheIds: z.array(z.string().uuid()), auditIds: z.array(z.string().uuid()) });
export type CleanupSelection = z.infer<typeof cleanupSelectionSchema>;
export const cleanupPreviewSchema = cleanupSelectionSchema.extend({ fingerprint: z.string().regex(/^[a-f0-9]{64}$/), previewToken: z.string(),
  hasMore: z.boolean(), counts: z.object({ candidates: z.number().int(), interviews: z.number().int(), caches: z.number().int(), auditEntries: z.number().int() }) });
export const retentionWorkspaceSchema = z.object({ policy: retentionPolicySchema, preview: cleanupPreviewSchema });
export const cleanupResultSchema = z.object({ candidatesErased: z.number().int(), interviewsErased: z.number().int(), cachesRemoved: z.number().int(), auditEntriesMinimized: z.number().int() });
export const retentionCommandPreviewSchema = z.object({ executed: z.literal(false), cutoffAt: z.string().datetime(), counts: cleanupPreviewSchema.shape.counts, hasMore: z.boolean() });
export const retentionCommandResultSchema = cleanupResultSchema.extend({ executed: z.literal(true), hadMoreAtPreview: z.boolean() });
export const auditQuerySchema = z.object({ limit: z.coerce.number().int().min(1).max(100).default(25), before: z.string().uuid().optional(),
  action: z.string().regex(/^[a-z_.]+$/).max(80).optional(), interviewId: z.string().uuid().optional() });
export const auditPageSchema = z.object({ items: z.array(z.object({ id: z.string().uuid(), action: z.string(), actorType: z.string(), actorId: z.string().nullable(),
  entityId: z.string().nullable(), interviewId: z.string().nullable(), at: z.string().datetime(), metadata: z.record(z.unknown()) })), nextCursor: z.string().uuid().nullable() });
export const governanceCandidatesSchema = z.object({ items: z.array(z.object({ id: z.string().uuid(), label: z.string(), jobTitle: z.string(), deleted: z.boolean(), retainedUntil: z.string().datetime() })), nextCursor: z.string().uuid().nullable() });

export function retentionDeadline(now: number, days: number, ceiling?: Date): Date {
  const validDays = retentionPolicySchema.shape.retentionDays.parse(days);
  return new Date(Math.min(now + validDays * 86400000, ceiling?.getTime() ?? Infinity));
}
export function assertRetentionCutoff(cutoff: Date, now = Date.now()): void {
  if (!Number.isFinite(cutoff.getTime()) || cutoff.getTime() > now) throw new DomainError("VALIDATION_FAILED", "清理截止时间不能在未来");
}
export function sanitizeAuditMetadata(metadata: Record<string, unknown>): Record<string, unknown> {
  function clean(value: unknown, depth: number): unknown {
    if (depth > 8) return "[TRUNCATED]";
    if (typeof value === "string") return redactText(value).text;
    if (typeof value === "number") { const text = String(value), masked = redactText(text).text; return masked === text ? value : masked; }
    if (value === null || typeof value === "boolean") return value;
    if (Array.isArray(value)) return value.slice(0, 100).map((item) => clean(item, depth + 1));
    if (typeof value === "object") return Object.fromEntries(Object.entries(value).slice(0, 100).map(([key, item]) => [key, /^(?:password|secret|apiKey|authorization|inviteToken|accessCode)$/i.test(key) ? "[REDACTED]" : clean(item, depth + 1)]));
    return null;
  }
  return z.record(z.unknown()).parse(clean(metadata, 0));
}
/** Erasure preserves the operation envelope and numeric human-score revisions, never free text or transcript copies. */
export function minimizedAuditMetadata(action: string, metadata: Record<string, unknown> | null): Record<string, unknown> {
  const result: Record<string, unknown> = { erased: true };
  if (action === "score.revised") {
    const values = z.object({ oldValue: z.enum(["1", "2", "3", "4", "5", "insufficient_evidence"]), newValue: z.enum(["1", "2", "3", "4", "5", "insufficient_evidence"]) }).safeParse(metadata);
    if (values.success) Object.assign(result, values.data);
  }
  return result;
}
/** Only server-owned response identities and resource paths determine cache ownership. */
export function cacheOwnershipHint(scope: string, payload: unknown): { kind: "candidate" | "interview" | "score"; id: string } | null {
  const path = /^(?:POST|PATCH) \/(candidates|interviews|scores)\/([0-9a-f-]{36})(?:\/|$)/i.exec(scope);
  if (path && z.string().uuid().safeParse(path[2]).success) return { kind: path[1] === "candidates" ? "candidate" : path[1] === "scores" ? "score" : "interview", id: path[2]! };
  if (scope === "POST /candidates") { const parsed = z.object({ id: z.string().uuid() }).safeParse(payload); if (parsed.success) return { kind: "candidate", id: parsed.data.id }; }
  if (scope === "POST /interviews") { const parsed = z.object({ interviewId: z.string().uuid() }).safeParse(payload); if (parsed.success) return { kind: "interview", id: parsed.data.interviewId }; }
  return null;
}
