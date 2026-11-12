-- App role for AI Interviewer: must remain NOSUPERUSER NOBYPASSRLS (Task 4 / D72).
-- Compose bootstrap only — passwords are placeholders; override via secrets in real deploys.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aii_app') THEN
    CREATE ROLE aii_app LOGIN PASSWORD 'aii_app_dev_only'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
END
$$;

GRANT CONNECT ON DATABASE aii TO aii_app;
GRANT USAGE ON SCHEMA public TO aii_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO aii_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aii_app;
