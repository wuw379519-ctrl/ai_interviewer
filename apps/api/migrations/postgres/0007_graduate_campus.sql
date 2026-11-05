ALTER TABLE "interviews" ADD COLUMN "recruitment_track" text DEFAULT 'general' NOT NULL;--> statement-breakpoint
ALTER TABLE "interviews" ADD COLUMN "graduate_verification" jsonb;--> statement-breakpoint
ALTER TABLE "jobs" ADD COLUMN "recruitment_track" text DEFAULT 'general' NOT NULL;--> statement-breakpoint
ALTER TABLE "questions" ADD COLUMN "topic_key" text;--> statement-breakpoint
ALTER TABLE "questions" ADD COLUMN "mandatory" boolean DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE "questions" ADD COLUMN "assessment_mode" text DEFAULT 'scored' NOT NULL;--> statement-breakpoint
ALTER TABLE "interviews" ADD CONSTRAINT "interviews_recruitment_track_valid" CHECK ("interviews"."recruitment_track" IN ('general', 'graduate_campus'));--> statement-breakpoint
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_recruitment_track_valid" CHECK ("jobs"."recruitment_track" IN ('general', 'graduate_campus'));--> statement-breakpoint
ALTER TABLE "questions" ADD CONSTRAINT "questions_assessment_mode_valid" CHECK ("questions"."assessment_mode" IN ('scored', 'information', 'eligibility'));