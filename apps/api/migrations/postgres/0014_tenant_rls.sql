-- PostgreSQL RLS: tenant_id (or ai_usage.tenant) must match session GUC app.tenant_id.
-- Application sets SET LOCAL via set_config('app.tenant_id', ..., true) at transaction start.
-- SQLite has no RLS; Commit 2 application filters remain the isolation layer there.

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON jobs
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidates FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON candidates
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE competencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE competencies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON competencies
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE interviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE interviews FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON interviews
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE questions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON questions
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE turns FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON turns
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON evidence
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE scores FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON scores
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE score_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE score_revisions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON score_revisions
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON reports
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE consents FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON consents
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE resumes FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON resumes
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON idempotency_keys
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE data_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON data_policies
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON audit_logs
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE interview_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE interview_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON interview_events
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE practice_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE practice_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON practice_sessions
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON users
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE role_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_bindings FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON role_bindings
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
--> statement-breakpoint
ALTER TABLE ai_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_usage FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON ai_usage
  USING (tenant = current_setting('app.tenant_id', true))
  WITH CHECK (tenant = current_setting('app.tenant_id', true));
