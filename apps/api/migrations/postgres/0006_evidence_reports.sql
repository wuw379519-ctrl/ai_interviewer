ALTER TABLE "reports" ADD COLUMN "question_scores" jsonb DEFAULT '[]'::jsonb NOT NULL;--> statement-breakpoint
ALTER TABLE "reports" ADD COLUMN "revision" integer DEFAULT 1 NOT NULL;--> statement-breakpoint
ALTER TABLE "reports" ADD CONSTRAINT "reports_revision_positive" CHECK ("reports"."revision" > 0);