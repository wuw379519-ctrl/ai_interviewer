CREATE TABLE IF NOT EXISTS proctor_logs (
    id CHAR(36) PRIMARY KEY NOT NULL,
    interview_id CHAR(36) NOT NULL,
    tenant_id CHAR(36) NOT NULL,
    signal_type TEXT NOT NULL,
    payload JSON NOT NULL,
    ts DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (signal_type IN (
        'tab_hidden', 'window_blur', 'answer_latency',
        'silence_ratio', 'volume_spike', 'speech_rate'
    )),
    FOREIGN KEY (interview_id) REFERENCES interviews (id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants (id)
)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS proctor_logs_interview_idx ON proctor_logs (interview_id, ts)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS proctor_logs_tenant_idx ON proctor_logs (tenant_id)
