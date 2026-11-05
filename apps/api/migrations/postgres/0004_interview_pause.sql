ALTER TABLE "interviews" ADD COLUMN "paused_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "interviews" ADD COLUMN "paused_total_sec" integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "interviews" ADD CONSTRAINT "interviews_paused_total_valid" CHECK ("interviews"."paused_total_sec" >= 0);