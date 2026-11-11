CREATE TABLE interview_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
    interview_id UUID NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT interview_events_seq_positive CHECK (seq > 0),
    CONSTRAINT interview_events_type_valid CHECK (event_type IN (
        'state_changed', 'question_asked', 'answer_received', 'consent_granted',
        'interrupted', 'score_computed', 'report_generated'
    ))
);
--> statement-breakpoint
CREATE UNIQUE INDEX interview_events_interview_seq_uq ON interview_events (interview_id, seq);
--> statement-breakpoint
CREATE INDEX interview_events_interview_idx ON interview_events (interview_id);
--> statement-breakpoint
CREATE TRIGGER touch_updated_at BEFORE UPDATE ON interview_events
  FOR EACH ROW EXECUTE FUNCTION aii_touch_updated_at();
