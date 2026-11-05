ALTER TABLE "interviews" ADD COLUMN "camera_required" boolean DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE "interviews" ADD COLUMN "camera_active" boolean DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE "interviews" ADD COLUMN "microphone_active" boolean DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE "interviews" ADD COLUMN "media_last_seen_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "interviews" ADD COLUMN "text_fallback" boolean DEFAULT false NOT NULL;