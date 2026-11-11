CREATE TABLE IF NOT EXISTS interview_events (
    id CHAR(32) PRIMARY KEY NOT NULL,
    interview_id CHAR(32) NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload JSON NOT NULL,
    ts DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (interview_id, seq),
    CHECK (seq > 0),
    CHECK (event_type IN (
        'state_changed', 'question_asked', 'answer_received', 'consent_granted',
        'interrupted', 'score_computed', 'report_generated'
    )),
    FOREIGN KEY (interview_id) REFERENCES interviews (id) ON DELETE CASCADE
)
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS interview_events_interview_idx ON interview_events (interview_id)
