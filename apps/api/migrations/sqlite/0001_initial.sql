CREATE TABLE audit_logs (
	id CHAR(32) NOT NULL, 
	actor_type TEXT NOT NULL, 
	actor_id TEXT, 
	action TEXT NOT NULL, 
	entity_type TEXT, 
	entity_id TEXT, 
	interview_id CHAR(32), 
	metadata JSON, 
	ip_hash TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
)
-- statement-breakpoint
CREATE TABLE data_policies (
	id VARCHAR NOT NULL, 
	retention_days INTEGER NOT NULL, 
	revision INTEGER NOT NULL, 
	updated_by TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (id = 'workspace' AND retention_days BETWEEN 1 AND 90 AND revision > 0)
)
-- statement-breakpoint
CREATE TABLE idempotency_keys (
	id CHAR(32) NOT NULL, 
	scope TEXT NOT NULL, 
	"key" TEXT NOT NULL, 
	request_hash TEXT NOT NULL, 
	status TEXT NOT NULL, 
	response_status INTEGER, 
	response_body JSON, 
	expires_at DATETIME NOT NULL, 
	owner_candidate_id CHAR(32), 
	owner_interview_id CHAR(32), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (scope, "key")
)
-- statement-breakpoint
CREATE TABLE jobs (
	id CHAR(32) NOT NULL, 
	title TEXT NOT NULL, 
	jd_text TEXT NOT NULL, 
	department TEXT, 
	seniority TEXT, 
	location TEXT, 
	status TEXT NOT NULL, 
	recruitment_track TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
)
-- statement-breakpoint
CREATE TABLE candidates (
	id CHAR(32) NOT NULL, 
	job_id CHAR(32) NOT NULL, 
	full_name TEXT NOT NULL, 
	email TEXT, 
	phone TEXT, 
	source TEXT, 
	retained_until DATETIME NOT NULL, 
	deleted_at DATETIME, 
	erased_at DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CHECK (erased_at IS NULL OR deleted_at IS NOT NULL), 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE RESTRICT
)
-- statement-breakpoint
CREATE TABLE competencies (
	id CHAR(32) NOT NULL, 
	job_id CHAR(32) NOT NULL, 
	name TEXT NOT NULL, 
	description TEXT NOT NULL, 
	weight_bp INTEGER NOT NULL, 
	bars_anchors JSON NOT NULL, 
	order_index INTEGER NOT NULL, 
	status TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (job_id, name), 
	CHECK (weight_bp BETWEEN 0 AND 10000), 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE CASCADE
)
-- statement-breakpoint
CREATE TABLE interviews (
	id CHAR(32) NOT NULL, 
	candidate_id CHAR(32) NOT NULL, 
	job_id CHAR(32) NOT NULL, 
	status TEXT NOT NULL, 
	duration_minutes INTEGER NOT NULL, 
	invite_token_hash TEXT, 
	invite_expires_at DATETIME, 
	plan_version TEXT, 
	retained_until DATETIME NOT NULL, 
	mode TEXT NOT NULL, 
	locale TEXT NOT NULL, 
	version INTEGER NOT NULL, 
	current_question_seq INTEGER NOT NULL, 
	started_at DATETIME, 
	finished_at DATETIME, 
	last_activity_at DATETIME, 
	paused_at DATETIME, 
	paused_total_sec INTEGER NOT NULL, 
	camera_required BOOLEAN NOT NULL, 
	camera_active BOOLEAN NOT NULL, 
	microphone_active BOOLEAN NOT NULL, 
	media_last_seen_at DATETIME, 
	text_fallback BOOLEAN NOT NULL, 
	recruitment_track TEXT NOT NULL, 
	graduate_verification JSON, 
	retention_days INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (invite_token_hash), 
	CHECK (duration_minutes IN (15,30,45)), 
	CHECK (retention_days BETWEEN 1 AND 90), 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE RESTRICT, 
	FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE RESTRICT
)
-- statement-breakpoint
CREATE TABLE resumes (
	id CHAR(32) NOT NULL, 
	candidate_id CHAR(32) NOT NULL, 
	file_name TEXT NOT NULL, 
	mime_type TEXT NOT NULL, 
	raw_text TEXT NOT NULL, 
	parsed JSON NOT NULL, 
	unverified_claims JSON NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(candidate_id) REFERENCES candidates (id) ON DELETE CASCADE
)
-- statement-breakpoint
CREATE TABLE consents (
	id CHAR(32) NOT NULL, 
	interview_id CHAR(32) NOT NULL, 
	consent_version TEXT NOT NULL, 
	consent_text_hash TEXT NOT NULL, 
	recording_allowed BOOLEAN NOT NULL, 
	consented_at DATETIME NOT NULL, 
	revoked_at DATETIME, 
	ip_hash TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (interview_id, consent_version), 
	FOREIGN KEY(interview_id) REFERENCES interviews (id) ON DELETE CASCADE
)
-- statement-breakpoint
CREATE TABLE questions (
	id CHAR(32) NOT NULL, 
	interview_id CHAR(32) NOT NULL, 
	competency_id CHAR(32) NOT NULL, 
	seq INTEGER NOT NULL, 
	prompt TEXT NOT NULL, 
	intent TEXT, 
	followups JSON NOT NULL, 
	time_budget_sec INTEGER NOT NULL, 
	status TEXT NOT NULL, 
	topic_key TEXT, 
	mandatory BOOLEAN NOT NULL, 
	assessment_mode TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (interview_id, seq), 
	CHECK (seq > 0 AND time_budget_sec > 0), 
	FOREIGN KEY(interview_id) REFERENCES interviews (id) ON DELETE CASCADE, 
	FOREIGN KEY(competency_id) REFERENCES competencies (id) ON DELETE RESTRICT
)
-- statement-breakpoint
CREATE TABLE reports (
	id CHAR(32) NOT NULL, 
	interview_id CHAR(32) NOT NULL, 
	overall_summary TEXT NOT NULL, 
	dimension_scores JSON NOT NULL, 
	question_scores JSON NOT NULL, 
	revision INTEGER NOT NULL, 
	highlights JSON NOT NULL, 
	risks JSON NOT NULL, 
	next_questions JSON NOT NULL, 
	recommendation TEXT NOT NULL, 
	recommendation_reason TEXT NOT NULL, 
	metadata JSON NOT NULL, 
	prompt_version TEXT, 
	retained_until DATETIME NOT NULL, 
	generated_at DATETIME NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (interview_id), 
	FOREIGN KEY(interview_id) REFERENCES interviews (id) ON DELETE CASCADE
)
-- statement-breakpoint
CREATE TABLE turns (
	id CHAR(32) NOT NULL, 
	interview_id CHAR(32) NOT NULL, 
	question_id CHAR(32), 
	seq INTEGER NOT NULL, 
	role TEXT NOT NULL, 
	content TEXT NOT NULL, 
	is_followup BOOLEAN NOT NULL, 
	parent_turn_id CHAR(32), 
	redacted BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT turns_interview_seq_uq UNIQUE (interview_id, seq), 
	UNIQUE (id, interview_id), 
	CHECK (seq > 0), 
	FOREIGN KEY(interview_id) REFERENCES interviews (id) ON DELETE CASCADE, 
	FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE SET NULL, 
	FOREIGN KEY(parent_turn_id) REFERENCES turns (id) ON DELETE SET NULL
)
-- statement-breakpoint
CREATE TABLE evidence (
	id CHAR(32) NOT NULL, 
	interview_id CHAR(32) NOT NULL, 
	turn_id CHAR(32) NOT NULL, 
	competency_id CHAR(32) NOT NULL, 
	quote TEXT NOT NULL, 
	start_offset INTEGER, 
	end_offset INTEGER, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (id, interview_id, competency_id), 
	FOREIGN KEY(turn_id, interview_id) REFERENCES turns (id, interview_id) ON DELETE CASCADE, 
	CHECK (length(trim(quote)) > 0), 
	FOREIGN KEY(interview_id) REFERENCES interviews (id) ON DELETE CASCADE, 
	FOREIGN KEY(turn_id) REFERENCES turns (id) ON DELETE CASCADE, 
	FOREIGN KEY(competency_id) REFERENCES competencies (id) ON DELETE RESTRICT
)
-- statement-breakpoint
CREATE TABLE scores (
	id CHAR(32) NOT NULL, 
	interview_id CHAR(32) NOT NULL, 
	competency_id CHAR(32) NOT NULL, 
	evidence_id CHAR(32), 
	value TEXT NOT NULL, 
	numeric_value INTEGER, 
	needs_review BOOLEAN NOT NULL, 
	rationale TEXT, 
	attempt INTEGER NOT NULL, 
	model TEXT, 
	prompt_version TEXT, 
	prompt_tokens INTEGER, 
	completion_tokens INTEGER, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (interview_id, competency_id, attempt), 
	FOREIGN KEY(evidence_id, interview_id, competency_id) REFERENCES evidence (id, interview_id, competency_id), 
	CHECK ((value = 'insufficient_evidence' AND evidence_id IS NULL AND numeric_value IS NULL) OR (value IN ('1','2','3','4','5') AND evidence_id IS NOT NULL AND numeric_value BETWEEN 1 AND 5 AND CAST(numeric_value AS TEXT)=value)), 
	CHECK (attempt IN (1,2)), 
	FOREIGN KEY(interview_id) REFERENCES interviews (id) ON DELETE CASCADE, 
	FOREIGN KEY(competency_id) REFERENCES competencies (id) ON DELETE RESTRICT, 
	FOREIGN KEY(evidence_id) REFERENCES evidence (id) ON DELETE SET NULL
)
-- statement-breakpoint
CREATE TABLE score_revisions (
	id CHAR(32) NOT NULL, 
	score_id CHAR(32) NOT NULL, 
	actor_id TEXT NOT NULL, 
	actor_name TEXT, 
	old_value TEXT NOT NULL, 
	new_value TEXT NOT NULL, 
	reason TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(score_id) REFERENCES scores (id) ON DELETE CASCADE
)
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS candidate_answer_gate BEFORE INSERT ON turns
    WHEN NEW.role='candidate' BEGIN
      SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM interviews i JOIN candidates c ON c.id=i.candidate_id
        JOIN consents s ON s.interview_id=i.id AND s.revoked_at IS NULL
        WHERE i.id=NEW.interview_id AND i.status IN ('interviewing','wrapping_up')
          AND c.deleted_at IS NULL AND julianday(i.retained_until)>julianday('now')
          AND julianday(c.retained_until)>julianday('now'))
        THEN RAISE(ABORT,'candidate_consent_gate') END;
    END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS evidence_quote_gate BEFORE INSERT ON evidence BEGIN
      SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM turns t JOIN questions q ON q.id=t.question_id
        WHERE t.id=NEW.turn_id AND t.interview_id=NEW.interview_id AND t.role='candidate'
          AND q.competency_id=NEW.competency_id AND instr(t.content,NEW.quote)>0 AND length(trim(NEW.quote))>0)
        THEN RAISE(ABORT,'invalid_evidence_quote') END;
    END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS cited_turn_immutable BEFORE UPDATE OF content,role,question_id,interview_id ON turns
    WHEN (NEW.content<>OLD.content OR NEW.role<>OLD.role OR NEW.interview_id<>OLD.interview_id OR coalesce(NEW.question_id,'')<>coalesce(OLD.question_id,''))
      AND EXISTS(SELECT 1 FROM evidence e WHERE e.turn_id=OLD.id)
    BEGIN SELECT RAISE(ABORT,'cited_turn_immutable'); END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS evidence_quote_update_gate BEFORE UPDATE ON evidence BEGIN
      SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM turns t JOIN questions q ON q.id=t.question_id
        WHERE t.id=NEW.turn_id AND t.interview_id=NEW.interview_id AND t.role='candidate'
          AND q.competency_id=NEW.competency_id AND instr(t.content,NEW.quote)>0 AND length(trim(NEW.quote))>0)
        THEN RAISE(ABORT,'invalid_evidence_quote') END;
    END
