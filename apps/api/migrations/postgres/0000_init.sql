CREATE TABLE "audit_logs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"actor_type" text NOT NULL,
	"actor_id" text,
	"action" text NOT NULL,
	"entity_type" text,
	"entity_id" text,
	"interview_id" uuid,
	"metadata" jsonb,
	"ip_hash" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "candidates" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"job_id" uuid NOT NULL,
	"full_name" text NOT NULL,
	"email" text,
	"phone" text,
	"source" text,
	"deleted_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "competencies" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"job_id" uuid NOT NULL,
	"name" text NOT NULL,
	"description" text NOT NULL,
	"weight_bp" integer NOT NULL,
	"bars_anchors" jsonb NOT NULL,
	"order_index" integer DEFAULT 0 NOT NULL,
	"status" text DEFAULT 'proposed' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "competencies_weight_bp_range" CHECK ("competencies"."weight_bp" >= 0 AND "competencies"."weight_bp" <= 10000),
	CONSTRAINT "competencies_bars_five_levels" CHECK (jsonb_array_length("competencies"."bars_anchors") = 5)
);
--> statement-breakpoint
CREATE TABLE "consents" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"interview_id" uuid NOT NULL,
	"consent_version" text NOT NULL,
	"consent_text_hash" text NOT NULL,
	"recording_allowed" boolean DEFAULT false NOT NULL,
	"consented_at" timestamp with time zone NOT NULL,
	"revoked_at" timestamp with time zone,
	"ip_hash" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "evidence" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"interview_id" uuid NOT NULL,
	"turn_id" uuid NOT NULL,
	"competency_id" uuid NOT NULL,
	"quote" text NOT NULL,
	"start_offset" integer,
	"end_offset" integer,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "evidence_quote_not_blank" CHECK (length(btrim("evidence"."quote")) > 0)
);
--> statement-breakpoint
CREATE TABLE "idempotency_keys" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"scope" text NOT NULL,
	"key" text NOT NULL,
	"request_hash" text NOT NULL,
	"status" text DEFAULT 'in_progress' NOT NULL,
	"response_status" integer,
	"response_body" jsonb,
	"expires_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "interviews" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"candidate_id" uuid NOT NULL,
	"job_id" uuid NOT NULL,
	"status" text DEFAULT 'created' NOT NULL,
	"duration_minutes" integer NOT NULL,
	"invite_token_hash" text,
	"invite_expires_at" timestamp with time zone,
	"plan_version" text,
	"retained_until" timestamp with time zone,
	"mode" text DEFAULT 'text' NOT NULL,
	"locale" text DEFAULT 'zh-CN' NOT NULL,
	"version" integer DEFAULT 0 NOT NULL,
	"current_question_seq" integer DEFAULT 0 NOT NULL,
	"started_at" timestamp with time zone,
	"finished_at" timestamp with time zone,
	"last_activity_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "interviews_duration_range" CHECK ("interviews"."duration_minutes" >= 5 AND "interviews"."duration_minutes" <= 120)
);
--> statement-breakpoint
CREATE TABLE "jobs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"title" text NOT NULL,
	"department" text,
	"seniority" text,
	"location" text,
	"jd_text" text NOT NULL,
	"status" text DEFAULT 'draft' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "questions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"interview_id" uuid NOT NULL,
	"competency_id" uuid NOT NULL,
	"seq" integer NOT NULL,
	"prompt" text NOT NULL,
	"intent" text,
	"followups" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"time_budget_sec" integer NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "questions_time_budget_positive" CHECK ("questions"."time_budget_sec" > 0)
);
--> statement-breakpoint
CREATE TABLE "reports" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"interview_id" uuid NOT NULL,
	"overall_summary" text NOT NULL,
	"dimension_scores" jsonb NOT NULL,
	"highlights" jsonb NOT NULL,
	"risks" jsonb NOT NULL,
	"next_questions" jsonb NOT NULL,
	"recommendation" text NOT NULL,
	"recommendation_reason" text NOT NULL,
	"metadata" jsonb NOT NULL,
	"prompt_version" text,
	"retained_until" timestamp with time zone,
	"generated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "resumes" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"candidate_id" uuid NOT NULL,
	"file_name" text NOT NULL,
	"mime_type" text NOT NULL,
	"raw_text" text NOT NULL,
	"parsed" jsonb NOT NULL,
	"unverified_claims" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "score_revisions" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"score_id" uuid NOT NULL,
	"actor_id" text NOT NULL,
	"actor_name" text,
	"old_value" text NOT NULL,
	"new_value" text NOT NULL,
	"reason" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "scores" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"interview_id" uuid NOT NULL,
	"competency_id" uuid NOT NULL,
	"evidence_id" uuid,
	"value" text NOT NULL,
	"numeric_value" integer,
	"needs_review" boolean DEFAULT false NOT NULL,
	"rationale" text,
	"attempt" integer DEFAULT 1 NOT NULL,
	"model" text,
	"prompt_version" text,
	"prompt_tokens" integer,
	"completion_tokens" integer,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "scores_attempt_range" CHECK ("scores"."attempt" IN (1, 2)),
	CONSTRAINT "scores_numeric_value_range" CHECK ("scores"."numeric_value" IS NULL OR ("scores"."numeric_value" >= 1 AND "scores"."numeric_value" <= 5)),
	CONSTRAINT "scores_evidence_consistency" CHECK (("scores"."value" = 'insufficient_evidence' AND "scores"."evidence_id" IS NULL AND "scores"."numeric_value" IS NULL)
          OR ("scores"."value" <> 'insufficient_evidence' AND "scores"."evidence_id" IS NOT NULL AND "scores"."numeric_value" IS NOT NULL))
);
--> statement-breakpoint
CREATE TABLE "turns" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"interview_id" uuid NOT NULL,
	"question_id" uuid,
	"seq" integer NOT NULL,
	"role" text NOT NULL,
	"content" text NOT NULL,
	"is_followup" boolean DEFAULT false NOT NULL,
	"parent_turn_id" uuid,
	"redacted" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "turns_seq_positive" CHECK ("turns"."seq" > 0)
);
--> statement-breakpoint
ALTER TABLE "candidates" ADD CONSTRAINT "candidates_job_id_jobs_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."jobs"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "competencies" ADD CONSTRAINT "competencies_job_id_jobs_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."jobs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "consents" ADD CONSTRAINT "consents_interview_id_interviews_id_fk" FOREIGN KEY ("interview_id") REFERENCES "public"."interviews"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence" ADD CONSTRAINT "evidence_interview_id_interviews_id_fk" FOREIGN KEY ("interview_id") REFERENCES "public"."interviews"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence" ADD CONSTRAINT "evidence_turn_id_turns_id_fk" FOREIGN KEY ("turn_id") REFERENCES "public"."turns"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence" ADD CONSTRAINT "evidence_competency_id_competencies_id_fk" FOREIGN KEY ("competency_id") REFERENCES "public"."competencies"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "interviews" ADD CONSTRAINT "interviews_candidate_id_candidates_id_fk" FOREIGN KEY ("candidate_id") REFERENCES "public"."candidates"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "interviews" ADD CONSTRAINT "interviews_job_id_jobs_id_fk" FOREIGN KEY ("job_id") REFERENCES "public"."jobs"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "questions" ADD CONSTRAINT "questions_interview_id_interviews_id_fk" FOREIGN KEY ("interview_id") REFERENCES "public"."interviews"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "questions" ADD CONSTRAINT "questions_competency_id_competencies_id_fk" FOREIGN KEY ("competency_id") REFERENCES "public"."competencies"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reports" ADD CONSTRAINT "reports_interview_id_interviews_id_fk" FOREIGN KEY ("interview_id") REFERENCES "public"."interviews"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "resumes" ADD CONSTRAINT "resumes_candidate_id_candidates_id_fk" FOREIGN KEY ("candidate_id") REFERENCES "public"."candidates"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "score_revisions" ADD CONSTRAINT "score_revisions_score_id_scores_id_fk" FOREIGN KEY ("score_id") REFERENCES "public"."scores"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "scores" ADD CONSTRAINT "scores_interview_id_interviews_id_fk" FOREIGN KEY ("interview_id") REFERENCES "public"."interviews"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "scores" ADD CONSTRAINT "scores_competency_id_competencies_id_fk" FOREIGN KEY ("competency_id") REFERENCES "public"."competencies"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "scores" ADD CONSTRAINT "scores_evidence_id_evidence_id_fk" FOREIGN KEY ("evidence_id") REFERENCES "public"."evidence"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "turns" ADD CONSTRAINT "turns_interview_id_interviews_id_fk" FOREIGN KEY ("interview_id") REFERENCES "public"."interviews"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "turns" ADD CONSTRAINT "turns_question_id_questions_id_fk" FOREIGN KEY ("question_id") REFERENCES "public"."questions"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "turns" ADD CONSTRAINT "turns_parent_turn_id_turns_id_fk" FOREIGN KEY ("parent_turn_id") REFERENCES "public"."turns"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "audit_logs_action_idx" ON "audit_logs" USING btree ("action");--> statement-breakpoint
CREATE INDEX "audit_logs_interview_idx" ON "audit_logs" USING btree ("interview_id");--> statement-breakpoint
CREATE INDEX "audit_logs_created_at_idx" ON "audit_logs" USING btree ("created_at");--> statement-breakpoint
CREATE INDEX "candidates_job_idx" ON "candidates" USING btree ("job_id");--> statement-breakpoint
CREATE INDEX "candidates_email_idx" ON "candidates" USING btree ("email");--> statement-breakpoint
CREATE INDEX "candidates_deleted_at_idx" ON "candidates" USING btree ("deleted_at");--> statement-breakpoint
CREATE UNIQUE INDEX "competencies_job_name_uq" ON "competencies" USING btree ("job_id","name");--> statement-breakpoint
CREATE INDEX "competencies_job_idx" ON "competencies" USING btree ("job_id");--> statement-breakpoint
CREATE UNIQUE INDEX "consents_interview_version_uq" ON "consents" USING btree ("interview_id","consent_version");--> statement-breakpoint
CREATE INDEX "consents_interview_idx" ON "consents" USING btree ("interview_id");--> statement-breakpoint
CREATE INDEX "evidence_interview_idx" ON "evidence" USING btree ("interview_id");--> statement-breakpoint
CREATE INDEX "evidence_turn_idx" ON "evidence" USING btree ("turn_id");--> statement-breakpoint
CREATE UNIQUE INDEX "idempotency_scope_key_uq" ON "idempotency_keys" USING btree ("scope","key");--> statement-breakpoint
CREATE INDEX "idempotency_expires_idx" ON "idempotency_keys" USING btree ("expires_at");--> statement-breakpoint
CREATE INDEX "interviews_candidate_idx" ON "interviews" USING btree ("candidate_id");--> statement-breakpoint
CREATE INDEX "interviews_status_idx" ON "interviews" USING btree ("status");--> statement-breakpoint
CREATE UNIQUE INDEX "interviews_invite_token_uq" ON "interviews" USING btree ("invite_token_hash");--> statement-breakpoint
CREATE INDEX "jobs_status_idx" ON "jobs" USING btree ("status");--> statement-breakpoint
CREATE INDEX "jobs_created_at_idx" ON "jobs" USING btree ("created_at");--> statement-breakpoint
CREATE UNIQUE INDEX "questions_interview_seq_uq" ON "questions" USING btree ("interview_id","seq");--> statement-breakpoint
CREATE INDEX "questions_interview_idx" ON "questions" USING btree ("interview_id");--> statement-breakpoint
CREATE UNIQUE INDEX "reports_interview_uq" ON "reports" USING btree ("interview_id");--> statement-breakpoint
CREATE INDEX "resumes_candidate_idx" ON "resumes" USING btree ("candidate_id");--> statement-breakpoint
CREATE INDEX "score_revisions_score_idx" ON "score_revisions" USING btree ("score_id");--> statement-breakpoint
CREATE UNIQUE INDEX "scores_interview_competency_attempt_uq" ON "scores" USING btree ("interview_id","competency_id","attempt");--> statement-breakpoint
CREATE INDEX "scores_interview_idx" ON "scores" USING btree ("interview_id");--> statement-breakpoint
CREATE INDEX "scores_evidence_idx" ON "scores" USING btree ("evidence_id");--> statement-breakpoint
CREATE UNIQUE INDEX "turns_interview_seq_uq" ON "turns" USING btree ("interview_id","seq");--> statement-breakpoint
CREATE INDEX "turns_interview_idx" ON "turns" USING btree ("interview_id");--> statement-breakpoint
CREATE INDEX "turns_question_idx" ON "turns" USING btree ("question_id");