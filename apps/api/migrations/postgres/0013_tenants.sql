CREATE TABLE tenants (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tenants_status_valid CHECK (status IN ('active', 'suspended', 'closed')),
    CONSTRAINT tenants_name_unique UNIQUE (name)
);
--> statement-breakpoint
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON tenants
  FOR EACH ROW EXECUTE FUNCTION aii_touch_updated_at();
--> statement-breakpoint
INSERT INTO tenants (id, name, status) VALUES
  ('00000000-0000-4000-8000-000000000001', 'default', 'active');
--> statement-breakpoint
CREATE TABLE users (
    id TEXT PRIMARY KEY NOT NULL,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_key TEXT NOT NULL,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT users_status_valid CHECK (status IN ('active', 'disabled')),
    CONSTRAINT users_tenant_key_uq UNIQUE (tenant_id, external_key)
);
--> statement-breakpoint
CREATE INDEX users_tenant_idx ON users (tenant_id);
--> statement-breakpoint
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION aii_touch_updated_at();
--> statement-breakpoint
CREATE TABLE role_bindings (
    id TEXT PRIMARY KEY NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT role_bindings_role_valid CHECK (role IN ('admin', 'recruiter')),
    CONSTRAINT role_bindings_user_tenant_role_uq UNIQUE (user_id, tenant_id, role)
);
--> statement-breakpoint
CREATE INDEX role_bindings_tenant_idx ON role_bindings (tenant_id);
--> statement-breakpoint
CREATE INDEX role_bindings_user_idx ON role_bindings (user_id);
--> statement-breakpoint
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON role_bindings
  FOR EACH ROW EXECUTE FUNCTION aii_touch_updated_at();
--> statement-breakpoint
INSERT INTO users (id, tenant_id, external_key, display_name, status) VALUES
  ('00000000-0000-4000-8000-000000000011', '00000000-0000-4000-8000-000000000001', 'admin', '工作空间管理员', 'active'),
  ('00000000-0000-4000-8000-000000000012', '00000000-0000-4000-8000-000000000001', 'recruiter', '工作空间招聘者', 'active');
--> statement-breakpoint
INSERT INTO role_bindings (id, user_id, tenant_id, role) VALUES
  ('00000000-0000-4000-8000-000000000021', '00000000-0000-4000-8000-000000000011', '00000000-0000-4000-8000-000000000001', 'admin'),
  ('00000000-0000-4000-8000-000000000022', '00000000-0000-4000-8000-000000000012', '00000000-0000-4000-8000-000000000001', 'recruiter');
--> statement-breakpoint
ALTER TABLE jobs ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE candidates ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE competencies ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE interviews ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE questions ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE turns ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE evidence ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE scores ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE score_revisions ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE reports ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE consents ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE resumes ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE idempotency_keys ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE data_policies ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE audit_logs ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE interview_events ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
ALTER TABLE practice_sessions ADD COLUMN tenant_id TEXT REFERENCES tenants(id);
--> statement-breakpoint
UPDATE jobs SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE candidates SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE competencies SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE interviews SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE questions SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE turns SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE evidence SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE scores SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE score_revisions SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE reports SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE consents SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE resumes SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE idempotency_keys SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE data_policies SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE audit_logs SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE interview_events SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE practice_sessions SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL;
--> statement-breakpoint
UPDATE ai_usage SET tenant = '00000000-0000-4000-8000-000000000001' WHERE tenant IS NULL;
--> statement-breakpoint
ALTER TABLE ai_usage ADD CONSTRAINT ai_usage_tenant_fkey FOREIGN KEY (tenant) REFERENCES tenants(id);
--> statement-breakpoint
CREATE INDEX jobs_tenant_idx ON jobs (tenant_id);
--> statement-breakpoint
CREATE INDEX candidates_tenant_idx ON candidates (tenant_id);
--> statement-breakpoint
CREATE INDEX interviews_tenant_idx ON interviews (tenant_id);
--> statement-breakpoint
CREATE INDEX audit_logs_tenant_idx ON audit_logs (tenant_id);
--> statement-breakpoint
CREATE INDEX interview_events_tenant_idx ON interview_events (tenant_id);
