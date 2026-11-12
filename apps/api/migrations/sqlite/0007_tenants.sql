CREATE TABLE IF NOT EXISTS tenants (
    id CHAR(36) PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('active', 'suspended', 'closed')),
    UNIQUE (name)
)
-- statement-breakpoint
INSERT OR IGNORE INTO tenants (id, name, status) VALUES
  ('00000000-0000-4000-8000-000000000001', 'default', 'active')
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS users (
    id CHAR(36) PRIMARY KEY NOT NULL,
    tenant_id CHAR(36) NOT NULL,
    external_key TEXT NOT NULL,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('active', 'disabled')),
    UNIQUE (tenant_id, external_key),
    FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS users_tenant_idx ON users (tenant_id)
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS role_bindings (
    id CHAR(36) PRIMARY KEY NOT NULL,
    user_id CHAR(36) NOT NULL,
    tenant_id CHAR(36) NOT NULL,
    role TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (role IN ('admin', 'recruiter')),
    UNIQUE (user_id, tenant_id, role),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS role_bindings_tenant_idx ON role_bindings (tenant_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS role_bindings_user_idx ON role_bindings (user_id)
-- statement-breakpoint
INSERT OR IGNORE INTO users (id, tenant_id, external_key, display_name, status) VALUES
  ('00000000-0000-4000-8000-000000000011', '00000000-0000-4000-8000-000000000001', 'admin', '工作空间管理员', 'active'),
  ('00000000-0000-4000-8000-000000000012', '00000000-0000-4000-8000-000000000001', 'recruiter', '工作空间招聘者', 'active')
-- statement-breakpoint
INSERT OR IGNORE INTO role_bindings (id, user_id, tenant_id, role) VALUES
  ('00000000-0000-4000-8000-000000000021', '00000000-0000-4000-8000-000000000011', '00000000-0000-4000-8000-000000000001', 'admin'),
  ('00000000-0000-4000-8000-000000000022', '00000000-0000-4000-8000-000000000012', '00000000-0000-4000-8000-000000000001', 'recruiter')
-- statement-breakpoint
ALTER TABLE jobs ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE candidates ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE competencies ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE interviews ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE questions ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE turns ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE evidence ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE scores ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE score_revisions ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE reports ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE consents ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE resumes ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE idempotency_keys ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE data_policies ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE audit_logs ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE interview_events ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
ALTER TABLE practice_sessions ADD COLUMN tenant_id CHAR(36) REFERENCES tenants (id)
-- statement-breakpoint
UPDATE jobs SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE candidates SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE competencies SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE interviews SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE questions SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE turns SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE evidence SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE scores SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE score_revisions SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE reports SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE consents SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE resumes SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE idempotency_keys SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE data_policies SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE audit_logs SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE interview_events SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE practice_sessions SET tenant_id = '00000000-0000-4000-8000-000000000001' WHERE tenant_id IS NULL
-- statement-breakpoint
UPDATE ai_usage SET tenant = '00000000-0000-4000-8000-000000000001' WHERE tenant IS NULL
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS jobs_tenant_idx ON jobs (tenant_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS candidates_tenant_idx ON candidates (tenant_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS interviews_tenant_idx ON interviews (tenant_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS audit_logs_tenant_idx ON audit_logs (tenant_id)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS interview_events_tenant_idx ON interview_events (tenant_id)
