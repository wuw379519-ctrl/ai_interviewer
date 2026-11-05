import { z } from "zod";
import { interviewStatusSchema, recruitmentTrackSchema } from "./schemas";
export const resourceIdentitySchema = z.object({ id: z.string().uuid() });

export const createdInterviewSchema = z.object({ interviewId: z.string().uuid(), inviteToken: z.string().min(20),
  status: interviewStatusSchema, questionCount: z.number().int(), planVersion: z.string(), inviteExpiresAt: z.string() });
export const interviewStateSchema = z.object({ interviewId: z.string().uuid(), status: interviewStatusSchema,
  retentionDays: z.number().int().min(1).max(90).default(90), retainedUntil: z.string().datetime().optional(),
  recruitmentTrack: recruitmentTrackSchema.optional(), mandatoryAsked: z.number().optional(), mandatoryTotal: z.number().optional(),
  durationMinutes: z.number(), startedAt: z.string().nullable(), remainingSec: z.number(), questionSeq: z.number(),
  followupsAsked: z.number(), totalQuestions: z.number(), answeredQuestions: z.number(), pausedAt: z.string().nullable(), jobTitle: z.string(),
  consentVersion: z.string(), consentText: z.string(), currentQuestion: z.object({ seq: z.number(), text: z.string(), intent: z.string(),
    mandatory: z.boolean().optional(), assessmentMode: z.enum(["scored", "information", "eligibility"]).optional(), topicKey: z.string().nullable().optional() }).nullable(),
  mode: z.enum(["text", "voice"]), cameraRequired: z.boolean(), cameraActive: z.boolean(), microphoneActive: z.boolean(), textFallback: z.boolean(),
  speechServerEnabled: z.boolean(), speechProcessorLabel: z.string(),
  ttsServerEnabled: z.boolean().default(false),
  turns: z.array(z.object({ seq: z.number(), role: z.string(), content: z.string(), isFollowup: z.boolean(), questionId: z.string().nullable() })),
});
export const turnResultSchema = z.object({ interviewId: z.string(), kind: z.enum(["ask_question", "ask_followup", "wrap_up", "complete"]),
  text: z.string(), questionSeq: z.number(), followupDepth: z.number(), status: interviewStatusSchema,
  remainingSec: z.number(), injectionSuspected: z.boolean(), injectionSignals: z.array(z.string()),
});
export type InterviewView = z.infer<typeof interviewStateSchema>;
