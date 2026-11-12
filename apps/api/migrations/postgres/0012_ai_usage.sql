CREATE TABLE ai_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
    tenant TEXT,
    provider TEXT NOT NULL,
    kind TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ai_usage_kind_valid CHECK (kind IN ('llm_tokens', 'asr_seconds', 'tts_chars')),
    CONSTRAINT ai_usage_amount_nonnegative CHECK (amount >= 0)
);
--> statement-breakpoint
CREATE INDEX ai_usage_provider_ts_idx ON ai_usage (provider, ts);
--> statement-breakpoint
CREATE INDEX ai_usage_tenant_ts_idx ON ai_usage (tenant, ts);
--> statement-breakpoint
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON ai_usage
  FOR EACH ROW EXECUTE FUNCTION aii_touch_updated_at();
