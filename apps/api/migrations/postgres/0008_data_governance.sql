CREATE TABLE "data_policies" (
	"id" text PRIMARY KEY DEFAULT 'workspace' NOT NULL,
	"retention_days" integer DEFAULT 90 NOT NULL,
	"revision" integer DEFAULT 1 NOT NULL,
	"updated_by" text DEFAULT 'system' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "data_policies_singleton" CHECK ("data_policies"."id" = 'workspace'),
	CONSTRAINT "data_policies_retention_valid" CHECK ("data_policies"."retention_days" BETWEEN 1 AND 90),
	CONSTRAINT "data_policies_revision_positive" CHECK ("data_policies"."revision" > 0)
);
--> statement-breakpoint
ALTER TABLE "candidates" ADD COLUMN "retained_until" timestamp with time zone DEFAULT now() + interval '90 days' NOT NULL;--> statement-breakpoint
ALTER TABLE "idempotency_keys" ADD COLUMN "owner_candidate_id" uuid;--> statement-breakpoint
ALTER TABLE "idempotency_keys" ADD COLUMN "owner_interview_id" uuid;--> statement-breakpoint
ALTER TABLE "interviews" ADD COLUMN "retention_days" integer DEFAULT 90 NOT NULL;--> statement-breakpoint
CREATE INDEX "candidates_retained_until_idx" ON "candidates" USING btree ("retained_until");--> statement-breakpoint
CREATE INDEX "idempotency_candidate_idx" ON "idempotency_keys" USING btree ("owner_candidate_id");--> statement-breakpoint
CREATE INDEX "idempotency_interview_idx" ON "idempotency_keys" USING btree ("owner_interview_id");--> statement-breakpoint
ALTER TABLE "interviews" ADD CONSTRAINT "interviews_retention_days_valid" CHECK ("interviews"."retention_days" BETWEEN 1 AND 90);
--> statement-breakpoint
INSERT INTO data_policies (id) VALUES ('workspace');
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON data_policies FOR EACH ROW EXECUTE FUNCTION aii_touch_updated_at();
UPDATE candidates SET retained_until = created_at + interval '90 days';
--> statement-breakpoint
-- Attribute pre-M4 response caches before they can be erased. Compare UUIDs as text, never cast untrusted JSON.
UPDATE idempotency_keys k SET owner_candidate_id = c.id
FROM candidates c WHERE k.scope = 'POST /candidates' AND k.response_body->>'id' = c.id::text;
UPDATE idempotency_keys k SET owner_candidate_id = c.id
FROM candidates c WHERE k.scope = 'POST /candidates/' || c.id::text || '/resume';
UPDATE idempotency_keys k SET owner_candidate_id = i.candidate_id, owner_interview_id = i.id
FROM interviews i WHERE k.scope LIKE '% /interviews/' || i.id::text || '/%'
OR (k.scope = 'POST /interviews' AND k.response_body->>'interviewId' = i.id::text);
UPDATE idempotency_keys k SET owner_candidate_id = i.candidate_id, owner_interview_id = i.id
FROM scores s JOIN interviews i ON i.id = s.interview_id WHERE k.scope = 'PATCH /scores/' || s.id::text;
