import { z } from "zod";
export const operationSchema = z.enum(["candidate_write", "turn", "state", "score", "transcribe", "plan"]);
export type Operation = z.infer<typeof operationSchema>;
export const operationsSchema = z.object({ startedAt: z.string().datetime(), sampledAt: z.string().datetime(), scope: z.literal("single-process"),
  items: z.array(z.object({ operation: operationSchema, requests: z.number().int().nonnegative(), failures: z.number().int().nonnegative(),
    clientErrors: z.number().int().nonnegative(), totalMs: z.number().nonnegative(), maxMs: z.number().nonnegative(),
    buckets: z.array(z.object({ leMs: z.number().nonnegative().nullable(), count: z.number().int().nonnegative() })).length(6) })).max(6) });
export type Operations = z.infer<typeof operationsSchema>;
