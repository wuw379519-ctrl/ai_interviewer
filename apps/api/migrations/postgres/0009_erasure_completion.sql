ALTER TABLE "candidates" ADD COLUMN "erased_at" timestamp with time zone;--> statement-breakpoint
CREATE INDEX "candidates_erased_at_idx" ON "candidates" USING btree ("erased_at");--> statement-breakpoint
ALTER TABLE "candidates" ADD CONSTRAINT "candidates_erased_requires_deleted" CHECK ("candidates"."erased_at" IS NULL OR "candidates"."deleted_at" IS NOT NULL);
--> statement-breakpoint
-- Only certify already-anonymous tombstones with no remaining business graph.
UPDATE candidates c SET erased_at = c.deleted_at
WHERE c.deleted_at IS NOT NULL AND c.full_name = '[已删除]' AND c.email IS NULL AND c.phone IS NULL AND c.source IS NULL
AND NOT EXISTS (SELECT 1 FROM interviews i WHERE i.candidate_id = c.id)
AND NOT EXISTS (SELECT 1 FROM resumes r WHERE r.candidate_id = c.id);
