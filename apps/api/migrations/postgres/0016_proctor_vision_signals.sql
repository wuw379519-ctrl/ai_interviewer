-- Task 9b: extend proctor_logs.signal_type for vision / camera stall signals.
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT con.conname AS name
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
    WHERE nsp.nspname = 'public'
      AND rel.relname = 'proctor_logs'
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) LIKE '%signal_type%'
  LOOP
    EXECUTE format('ALTER TABLE proctor_logs DROP CONSTRAINT %I', r.name);
  END LOOP;
END
$$;
--> statement-breakpoint
ALTER TABLE proctor_logs ADD CONSTRAINT proctor_logs_signal_type_check CHECK (
  signal_type IN (
    'tab_hidden', 'window_blur', 'answer_latency',
    'silence_ratio', 'volume_spike', 'speech_rate',
    'no_face', 'multi_face', 'camera_stall', 'camera_lost'
  )
);
