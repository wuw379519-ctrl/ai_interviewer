-- Align SQLite lookup indexes with the PostgreSQL 0000/0008/0009 index set.
-- Table-level UNIQUE constraints already cover the unique indexes; this file adds non-unique helpers.
CREATE INDEX IF NOT EXISTS audit_logs_action_idx ON audit_logs (action)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS audit_logs_interview_idx ON audit_logs (interview_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS audit_logs_created_at_idx ON audit_logs (created_at)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS candidates_job_idx ON candidates (job_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS candidates_email_idx ON candidates (email)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS candidates_deleted_at_idx ON candidates (deleted_at)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS candidates_retained_until_idx ON candidates (retained_until)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS candidates_erased_at_idx ON candidates (erased_at)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS competencies_job_idx ON competencies (job_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS consents_interview_idx ON consents (interview_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS evidence_interview_idx ON evidence (interview_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS evidence_turn_idx ON evidence (turn_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS idempotency_expires_idx ON idempotency_keys (expires_at)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS idempotency_candidate_idx ON idempotency_keys (owner_candidate_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS idempotency_interview_idx ON idempotency_keys (owner_interview_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS interviews_candidate_idx ON interviews (candidate_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS interviews_status_idx ON interviews (status)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs (created_at)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS questions_interview_idx ON questions (interview_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS resumes_candidate_idx ON resumes (candidate_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS score_revisions_score_idx ON score_revisions (score_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS scores_interview_idx ON scores (interview_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS scores_evidence_idx ON scores (evidence_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS turns_interview_idx ON turns (interview_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS turns_question_idx ON turns (question_id)
