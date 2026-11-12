CREATE TABLE IF NOT EXISTS ai_usage (
    id CHAR(32) PRIMARY KEY NOT NULL,
    tenant TEXT,
    provider TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount REAL NOT NULL,
    ts DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (kind IN ('llm_tokens', 'asr_seconds', 'tts_chars')),
    CHECK (amount >= 0)
)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS ai_usage_provider_ts_idx ON ai_usage (provider, ts)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS ai_usage_tenant_ts_idx ON ai_usage (tenant, ts)
