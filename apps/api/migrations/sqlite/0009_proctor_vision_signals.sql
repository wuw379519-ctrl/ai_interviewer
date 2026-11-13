-- Task 9b: SQLite cannot ALTER CHECK — rebuild proctor_logs with extended signal_type.
CREATE TABLE proctor_logs__vision (
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
        'silence_ratio', 'volume_spike', 'speech_rate',
        'no_face', 'multi_face', 'camera_stall', 'camera_lost'
    )),
    FOREIGN KEY (interview_id) REFERENCES interviews (id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants (id)
)
-- statement-breakpoint
INSERT INTO proctor_logs__vision (
    id, interview_id, tenant_id, signal_type, payload, ts, created_at, updated_at
)
SELECT id, interview_id, tenant_id, signal_type, payload, ts, created_at, updated_at
FROM proctor_logs
-- statement-breakpoint
DROP TABLE proctor_logs
-- statement-breakpoint
ALTER TABLE proctor_logs__vision RENAME TO proctor_logs
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS proctor_logs_interview_idx ON proctor_logs (interview_id, ts)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS proctor_logs_tenant_idx ON proctor_logs (tenant_id)
