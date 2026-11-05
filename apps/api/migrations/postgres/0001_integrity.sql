ALTER TABLE "interviews" DROP CONSTRAINT "interviews_duration_range";--> statement-breakpoint
CREATE UNIQUE INDEX "evidence_identity_uq" ON "evidence" USING btree ("id","interview_id","competency_id");--> statement-breakpoint
CREATE UNIQUE INDEX "turns_id_interview_uq" ON "turns" USING btree ("id","interview_id");--> statement-breakpoint
ALTER TABLE "evidence" ADD CONSTRAINT "evidence_turn_interview_fk" FOREIGN KEY ("turn_id","interview_id") REFERENCES "public"."turns"("id","interview_id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "scores" ADD CONSTRAINT "scores_evidence_identity_fk" FOREIGN KEY ("evidence_id","interview_id","competency_id") REFERENCES "public"."evidence"("id","interview_id","competency_id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "competencies" ADD CONSTRAINT "competencies_bars_levels_valid" CHECK ("competencies"."bars_anchors" @> '[{"level":1},{"level":2},{"level":3},{"level":4},{"level":5}]'::jsonb);--> statement-breakpoint
ALTER TABLE "competencies" ADD CONSTRAINT "competencies_status_valid" CHECK ("competencies"."status" IN ('proposed', 'confirmed'));--> statement-breakpoint
ALTER TABLE "consents" ADD CONSTRAINT "consents_version_required" CHECK (length(btrim("consents"."consent_version")) > 0 AND length(btrim("consents"."consent_text_hash")) > 0);--> statement-breakpoint
ALTER TABLE "consents" ADD CONSTRAINT "consents_revocation_order" CHECK ("consents"."revoked_at" IS NULL OR "consents"."revoked_at" >= "consents"."consented_at");--> statement-breakpoint
ALTER TABLE "evidence" ADD CONSTRAINT "evidence_offsets_valid" CHECK (("evidence"."start_offset" IS NULL AND "evidence"."end_offset" IS NULL) OR ("evidence"."start_offset" IS NOT NULL AND "evidence"."end_offset" IS NOT NULL AND "evidence"."start_offset" >= 0 AND "evidence"."end_offset" > "evidence"."start_offset"));--> statement-breakpoint
ALTER TABLE "idempotency_keys" ADD CONSTRAINT "idempotency_status_valid" CHECK ("idempotency_keys"."status" IN ('in_progress', 'completed'));--> statement-breakpoint
ALTER TABLE "interviews" ADD CONSTRAINT "interviews_status_valid" CHECK ("interviews"."status" IN ('created', 'invited', 'consented', 'warmup', 'interviewing', 'wrapping_up', 'scoring', 'report_ready', 'reviewed', 'cancelled'));--> statement-breakpoint
ALTER TABLE "interviews" ADD CONSTRAINT "interviews_progress_valid" CHECK ("interviews"."version" >= 0 AND "interviews"."current_question_seq" >= 0);--> statement-breakpoint
ALTER TABLE "interviews" ADD CONSTRAINT "interviews_mode_valid" CHECK ("interviews"."mode" IN ('text', 'voice'));--> statement-breakpoint
ALTER TABLE "interviews" ADD CONSTRAINT "interviews_duration_range" CHECK ("interviews"."duration_minutes" IN (15, 30, 45));--> statement-breakpoint
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_status_valid" CHECK ("jobs"."status" IN ('draft', 'active', 'archived'));--> statement-breakpoint
ALTER TABLE "questions" ADD CONSTRAINT "questions_seq_positive" CHECK ("questions"."seq" > 0);--> statement-breakpoint
ALTER TABLE "questions" ADD CONSTRAINT "questions_status_valid" CHECK ("questions"."status" IN ('pending', 'asked', 'answered', 'skipped'));--> statement-breakpoint
ALTER TABLE "reports" ADD CONSTRAINT "reports_recommendation_valid" CHECK ("reports"."recommendation" IN ('strong_yes', 'yes', 'mixed', 'no'));--> statement-breakpoint
ALTER TABLE "score_revisions" ADD CONSTRAINT "score_revisions_reason_required" CHECK (length(btrim("score_revisions"."reason")) > 0 AND length(btrim("score_revisions"."actor_id")) > 0);--> statement-breakpoint
ALTER TABLE "score_revisions" ADD CONSTRAINT "score_revisions_values_valid" CHECK ("score_revisions"."old_value" IN ('1', '2', '3', '4', '5', 'insufficient_evidence') AND "score_revisions"."new_value" IN ('1', '2', '3', '4', '5', 'insufficient_evidence'));--> statement-breakpoint
ALTER TABLE "scores" ADD CONSTRAINT "scores_value_valid" CHECK ("scores"."value" IN ('1', '2', '3', '4', '5', 'insufficient_evidence'));--> statement-breakpoint
ALTER TABLE "scores" ADD CONSTRAINT "scores_numeric_matches_value" CHECK ("scores"."value" = 'insufficient_evidence' OR "scores"."value" = "scores"."numeric_value"::text);--> statement-breakpoint
ALTER TABLE "turns" ADD CONSTRAINT "turns_role_valid" CHECK ("turns"."role" IN ('interviewer', 'candidate', 'system'));
