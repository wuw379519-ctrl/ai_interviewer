-- tenant_id must be TEXT to match tenants.id (0013); UUID breaks the FK on Postgres.
CREATE TABLE IF NOT EXISTS proctor_logs (
    id UUID PRIMARY KEY NOT NULL,
    interview_id UUID NOT NULL REFERENCES interviews (id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL REFERENCES tenants (id),
    signal_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (signal_type IN (
        'tab_hidden', 'window_blur', 'answer_latency',
        'silence_ratio', 'volume_spike', 'speech_rate'
    ))
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS proctor_logs_interview_idx ON proctor_logs (interview_id, ts);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS proctor_logs_tenant_idx ON proctor_logs (tenant_id);
--> statement-breakpoint
ALTER TABLE proctor_logs ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint
ALTER TABLE proctor_logs FORCE ROW LEVEL SECURITY;
--> statement-breakpoint
CREATE POLICY tenant_isolation ON proctor_logs
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
