ALTER TABLE "interviews" ALTER COLUMN "retained_until" SET DEFAULT now() + interval '90 days';--> statement-breakpoint
UPDATE "interviews" SET "retained_until" = "created_at" + interval '90 days'
  WHERE "retained_until" IS NULL OR "retained_until" > "created_at" + interval '90 days';--> statement-breakpoint
ALTER TABLE "interviews" ALTER COLUMN "retained_until" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "reports" ALTER COLUMN "retained_until" SET DEFAULT now() + interval '90 days';--> statement-breakpoint
UPDATE "reports" SET "retained_until" = "created_at" + interval '90 days'
  WHERE "retained_until" IS NULL OR "retained_until" > "created_at" + interval '90 days';--> statement-breakpoint
ALTER TABLE "reports" ALTER COLUMN "retained_until" SET NOT NULL;
