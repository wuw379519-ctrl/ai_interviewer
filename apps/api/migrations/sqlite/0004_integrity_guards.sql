-- SQLite cannot ADD CHECK to existing tables; mirror PostgreSQL 0001/0004/0006/0007
-- integrity constraints with BEFORE INSERT/UPDATE triggers. Existing squash DDL already
-- carries duration/retention/evidence/attempt checks and consent/evidence quote gates.
CREATE TRIGGER IF NOT EXISTS jobs_status_valid BEFORE INSERT ON jobs
BEGIN
  SELECT CASE WHEN NEW.status NOT IN ('draft', 'active', 'archived')
    THEN RAISE(ABORT, 'jobs_status_valid') END;
  SELECT CASE WHEN NEW.recruitment_track NOT IN ('general', 'graduate_campus')
    THEN RAISE(ABORT, 'jobs_recruitment_track_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS jobs_status_valid_update BEFORE UPDATE OF status, recruitment_track ON jobs
BEGIN
  SELECT CASE WHEN NEW.status NOT IN ('draft', 'active', 'archived')
    THEN RAISE(ABORT, 'jobs_status_valid') END;
  SELECT CASE WHEN NEW.recruitment_track NOT IN ('general', 'graduate_campus')
    THEN RAISE(ABORT, 'jobs_recruitment_track_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS competencies_status_valid BEFORE INSERT ON competencies
BEGIN
  SELECT CASE WHEN NEW.status NOT IN ('proposed', 'confirmed')
    THEN RAISE(ABORT, 'competencies_status_valid') END;
  SELECT CASE WHEN json_array_length(NEW.bars_anchors) <> 5
    THEN RAISE(ABORT, 'competencies_bars_five_levels') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS competencies_status_valid_update BEFORE UPDATE OF status, bars_anchors ON competencies
BEGIN
  SELECT CASE WHEN NEW.status NOT IN ('proposed', 'confirmed')
    THEN RAISE(ABORT, 'competencies_status_valid') END;
  SELECT CASE WHEN json_array_length(NEW.bars_anchors) <> 5
    THEN RAISE(ABORT, 'competencies_bars_five_levels') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS consents_integrity BEFORE INSERT ON consents
BEGIN
  SELECT CASE WHEN length(trim(NEW.consent_version)) = 0 OR length(trim(NEW.consent_text_hash)) = 0
    THEN RAISE(ABORT, 'consents_version_required') END;
  SELECT CASE WHEN NEW.revoked_at IS NOT NULL AND NEW.revoked_at < NEW.consented_at
    THEN RAISE(ABORT, 'consents_revocation_order') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS consents_integrity_update BEFORE UPDATE ON consents
BEGIN
  SELECT CASE WHEN length(trim(NEW.consent_version)) = 0 OR length(trim(NEW.consent_text_hash)) = 0
    THEN RAISE(ABORT, 'consents_version_required') END;
  SELECT CASE WHEN NEW.revoked_at IS NOT NULL AND NEW.revoked_at < NEW.consented_at
    THEN RAISE(ABORT, 'consents_revocation_order') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS evidence_offsets_valid BEFORE INSERT ON evidence
BEGIN
  SELECT CASE WHEN NOT (
      (NEW.start_offset IS NULL AND NEW.end_offset IS NULL)
      OR (NEW.start_offset IS NOT NULL AND NEW.end_offset IS NOT NULL
          AND NEW.start_offset >= 0 AND NEW.end_offset > NEW.start_offset)
    ) THEN RAISE(ABORT, 'evidence_offsets_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS evidence_offsets_valid_update BEFORE UPDATE OF start_offset, end_offset ON evidence
BEGIN
  SELECT CASE WHEN NOT (
      (NEW.start_offset IS NULL AND NEW.end_offset IS NULL)
      OR (NEW.start_offset IS NOT NULL AND NEW.end_offset IS NOT NULL
          AND NEW.start_offset >= 0 AND NEW.end_offset > NEW.start_offset)
    ) THEN RAISE(ABORT, 'evidence_offsets_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS idempotency_status_valid BEFORE INSERT ON idempotency_keys
BEGIN
  SELECT CASE WHEN NEW.status NOT IN ('in_progress', 'completed')
    THEN RAISE(ABORT, 'idempotency_status_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS idempotency_status_valid_update BEFORE UPDATE OF status ON idempotency_keys
BEGIN
  SELECT CASE WHEN NEW.status NOT IN ('in_progress', 'completed')
    THEN RAISE(ABORT, 'idempotency_status_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS interviews_integrity BEFORE INSERT ON interviews
BEGIN
  SELECT CASE WHEN NEW.status NOT IN (
      'created', 'invited', 'consented', 'warmup', 'interviewing',
      'wrapping_up', 'scoring', 'report_ready', 'reviewed', 'cancelled'
    ) THEN RAISE(ABORT, 'interviews_status_valid') END;
  SELECT CASE WHEN NEW.version < 0 OR NEW.current_question_seq < 0
    THEN RAISE(ABORT, 'interviews_progress_valid') END;
  SELECT CASE WHEN NEW.mode NOT IN ('text', 'voice')
    THEN RAISE(ABORT, 'interviews_mode_valid') END;
  SELECT CASE WHEN NEW.paused_total_sec < 0
    THEN RAISE(ABORT, 'interviews_paused_total_valid') END;
  SELECT CASE WHEN NEW.recruitment_track NOT IN ('general', 'graduate_campus')
    THEN RAISE(ABORT, 'interviews_recruitment_track_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS interviews_integrity_update BEFORE UPDATE OF
  status, version, current_question_seq, mode, paused_total_sec, recruitment_track ON interviews
BEGIN
  SELECT CASE WHEN NEW.status NOT IN (
      'created', 'invited', 'consented', 'warmup', 'interviewing',
      'wrapping_up', 'scoring', 'report_ready', 'reviewed', 'cancelled'
    ) THEN RAISE(ABORT, 'interviews_status_valid') END;
  SELECT CASE WHEN NEW.version < 0 OR NEW.current_question_seq < 0
    THEN RAISE(ABORT, 'interviews_progress_valid') END;
  SELECT CASE WHEN NEW.mode NOT IN ('text', 'voice')
    THEN RAISE(ABORT, 'interviews_mode_valid') END;
  SELECT CASE WHEN NEW.paused_total_sec < 0
    THEN RAISE(ABORT, 'interviews_paused_total_valid') END;
  SELECT CASE WHEN NEW.recruitment_track NOT IN ('general', 'graduate_campus')
    THEN RAISE(ABORT, 'interviews_recruitment_track_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS questions_integrity BEFORE INSERT ON questions
BEGIN
  SELECT CASE WHEN NEW.status NOT IN ('pending', 'asked', 'answered', 'skipped')
    THEN RAISE(ABORT, 'questions_status_valid') END;
  SELECT CASE WHEN NEW.assessment_mode NOT IN ('scored', 'information', 'eligibility')
    THEN RAISE(ABORT, 'questions_assessment_mode_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS questions_integrity_update BEFORE UPDATE OF status, assessment_mode ON questions
BEGIN
  SELECT CASE WHEN NEW.status NOT IN ('pending', 'asked', 'answered', 'skipped')
    THEN RAISE(ABORT, 'questions_status_valid') END;
  SELECT CASE WHEN NEW.assessment_mode NOT IN ('scored', 'information', 'eligibility')
    THEN RAISE(ABORT, 'questions_assessment_mode_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS reports_integrity BEFORE INSERT ON reports
BEGIN
  SELECT CASE WHEN NEW.recommendation NOT IN ('strong_yes', 'yes', 'mixed', 'no')
    THEN RAISE(ABORT, 'reports_recommendation_valid') END;
  SELECT CASE WHEN NEW.revision <= 0
    THEN RAISE(ABORT, 'reports_revision_positive') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS reports_integrity_update BEFORE UPDATE OF recommendation, revision ON reports
BEGIN
  SELECT CASE WHEN NEW.recommendation NOT IN ('strong_yes', 'yes', 'mixed', 'no')
    THEN RAISE(ABORT, 'reports_recommendation_valid') END;
  SELECT CASE WHEN NEW.revision <= 0
    THEN RAISE(ABORT, 'reports_revision_positive') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS score_revisions_integrity BEFORE INSERT ON score_revisions
BEGIN
  SELECT CASE WHEN length(trim(NEW.reason)) = 0 OR length(trim(NEW.actor_id)) = 0
    THEN RAISE(ABORT, 'score_revisions_reason_required') END;
  SELECT CASE WHEN NEW.old_value NOT IN ('1', '2', '3', '4', '5', 'insufficient_evidence')
      OR NEW.new_value NOT IN ('1', '2', '3', '4', '5', 'insufficient_evidence')
    THEN RAISE(ABORT, 'score_revisions_values_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS score_revisions_integrity_update BEFORE UPDATE ON score_revisions
BEGIN
  SELECT CASE WHEN length(trim(NEW.reason)) = 0 OR length(trim(NEW.actor_id)) = 0
    THEN RAISE(ABORT, 'score_revisions_reason_required') END;
  SELECT CASE WHEN NEW.old_value NOT IN ('1', '2', '3', '4', '5', 'insufficient_evidence')
      OR NEW.new_value NOT IN ('1', '2', '3', '4', '5', 'insufficient_evidence')
    THEN RAISE(ABORT, 'score_revisions_values_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS turns_role_valid BEFORE INSERT ON turns
BEGIN
  SELECT CASE WHEN NEW.role NOT IN ('interviewer', 'candidate', 'system')
    THEN RAISE(ABORT, 'turns_role_valid') END;
END
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS turns_role_valid_update BEFORE UPDATE OF role ON turns
BEGIN
  SELECT CASE WHEN NEW.role NOT IN ('interviewer', 'candidate', 'system')
    THEN RAISE(ABORT, 'turns_role_valid') END;
END
