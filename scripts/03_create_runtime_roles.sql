-- ===========================================================================
-- TASK 3 — create the runtime roles.
--
-- RUN THIS IN: pgAdmin Query Tool, connected to the "adw_dev" database, using
--              your ADMIN connection. Creating roles requires privileges that
--              adw_owner intentionally does not have (it is NOCREATEROLE), so
--              this cannot run from a migration.
--
-- Plain SQL only — no psql meta-commands.
--
-- Roles per ARCHITECTURE.md §25 and D18/G3:
--
--   adw_owner    already created in Task 1. Owns tables, runs Alembic.
--   adw_app      API and workers. Constrained by RLS on every tenant table.
--   adw_anchor   anchoring job. Reads chain-head hashes only (I13).
--   adw_auditor  read-only audit access.
--
-- None of them is a superuser and none holds BYPASSRLS. That is the whole
-- point: RLS does not apply to a superuser or to a BYPASSRLS role, so either
-- attribute would silently void every policy in the system.
-- ===========================================================================

DO $$
BEGIN
    IF current_database() <> 'adw_dev' THEN
        RAISE EXCEPTION
            'Connected to "%", expected "adw_dev". Reconnect before running this script.',
            current_database();
    END IF;
END
$$;


-- --- Create the three roles, without passwords. --------------------------
-- Idempotent. Passwords are set separately (see the note at the end) so they
-- never enter your pgAdmin query history.
DO $$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['adw_app', 'adw_anchor', 'adw_auditor'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format(
                'CREATE ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB '
                'NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
                role_name
            );
            RAISE NOTICE 'Created role % (no password yet).', role_name;
        ELSE
            RAISE NOTICE 'Role % already exists; attributes left unchanged.', role_name;
        END IF;
    END LOOP;
END
$$;


-- --- Connect and schema access. ------------------------------------------
GRANT CONNECT ON DATABASE adw_dev TO adw_app, adw_anchor, adw_auditor;
GRANT USAGE ON SCHEMA public TO adw_app, adw_anchor, adw_auditor;

-- USAGE on the schema alone grants no access to any table. Table privileges
-- are granted per table, deliberately, as each is created.


-- --- Default privileges for the runtime role only. -----------------------
-- Tables created by adw_owner become readable and writable by adw_app.
-- RLS then constrains *which rows* adw_app may touch.
ALTER DEFAULT PRIVILEGES FOR ROLE adw_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO adw_app;

ALTER DEFAULT PRIVILEGES FOR ROLE adw_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO adw_app;

-- adw_anchor and adw_auditor deliberately receive NO default privileges.
-- Their access is granted per table, narrowly:
--   adw_anchor   -> SELECT on chain_head, INSERT on anchor_record  (Task 6)
--   adw_auditor  -> SELECT on the chain and anchor tables          (Task 5/6)
-- A default grant here would hand them blanket access to every future table,
-- which is exactly what I13 forbids.


-- --- Verify. -------------------------------------------------------------
SELECT
    rolname          AS role,
    rolcanlogin      AS can_login,
    rolsuper         AS is_superuser,
    rolbypassrls     AS bypasses_rls,
    rolcreatedb      AS can_create_db,
    rolcreaterole    AS can_create_role
FROM pg_roles
WHERE rolname IN ('adw_owner', 'adw_app', 'adw_anchor', 'adw_auditor')
ORDER BY rolname;

-- Expected for all four: can_login = true, and false everywhere else.


-- ===========================================================================
-- SETTING PASSWORDS
--
-- Preferred: pgAdmin UI -> Login/Group Roles -> <role> -> Properties ->
--            Definition -> Password. Keeps them out of query history.
--
-- Or by SQL, one role at a time, then clear the Query Tool history:
--   ALTER ROLE adw_app     WITH PASSWORD 'REPLACE_ME';
--   ALTER ROLE adw_anchor  WITH PASSWORD 'REPLACE_ME';
--   ALTER ROLE adw_auditor WITH PASSWORD 'REPLACE_ME';
--
-- Put the adw_app password in .env as ADW_DATABASE_URL. Keep adw_owner in
-- ADW_MIGRATION_DATABASE_URL: Alembic needs DDL, the application must not have it.
-- ===========================================================================
