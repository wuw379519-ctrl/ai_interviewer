-- Database safety gates. Drizzle snapshots track tables/checks/FKs; these
-- PostgreSQL trigger functions are maintained in this custom migration.
CREATE FUNCTION aii_guard_candidate_answer() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE current_status text;
BEGIN
  IF NEW.role = 'candidate' THEN
    SELECT status INTO current_status FROM interviews WHERE id = NEW.interview_id FOR UPDATE;
    IF current_status IS NULL OR current_status NOT IN ('interviewing', 'wrapping_up') THEN
      RAISE EXCEPTION 'candidate_answer_requires_active_interview' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM consents WHERE interview_id = NEW.interview_id
        AND revoked_at IS NULL AND consented_at <= now()
    ) THEN
      RAISE EXCEPTION 'candidate_answer_requires_consent' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER candidate_answer_gate BEFORE INSERT OR UPDATE OF content, role, interview_id ON turns
  FOR EACH ROW EXECUTE FUNCTION aii_guard_candidate_answer();
--> statement-breakpoint
CREATE FUNCTION aii_guard_evidence_quote() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_content text;
BEGIN
  SELECT content INTO source_content FROM turns
    WHERE id = NEW.turn_id AND interview_id = NEW.interview_id AND role = 'candidate' FOR SHARE;
  IF source_content IS NULL OR position(NEW.quote IN source_content) = 0 THEN
    RAISE EXCEPTION 'evidence_quote_requires_verbatim_candidate_turn' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER evidence_quote_gate BEFORE INSERT OR UPDATE ON evidence
  FOR EACH ROW EXECUTE FUNCTION aii_guard_evidence_quote();
--> statement-breakpoint
CREATE FUNCTION aii_guard_evidenced_turn() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM evidence WHERE turn_id = OLD.id)
     AND (NEW.content IS DISTINCT FROM OLD.content OR NEW.role IS DISTINCT FROM OLD.role) THEN
    RAISE EXCEPTION 'evidenced_turn_is_immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
--> statement-breakpoint
CREATE TRIGGER evidenced_turn_gate BEFORE UPDATE OF content, role ON turns
  FOR EACH ROW EXECUTE FUNCTION aii_guard_evidenced_turn();
--> statement-breakpoint
CREATE FUNCTION aii_touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = clock_timestamp();
  RETURN NEW;
END;
$$;
--> statement-breakpoint
DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'jobs', 'competencies', 'candidates', 'resumes', 'interviews', 'questions',
    'turns', 'evidence', 'scores', 'reports', 'consents', 'audit_logs',
    'score_revisions', 'idempotency_keys'
  ] LOOP
    EXECUTE format('CREATE TRIGGER touch_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION aii_touch_updated_at()', table_name);
  END LOOP;
END;
$$;
