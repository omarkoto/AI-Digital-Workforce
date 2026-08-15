-- ===========================================================================
-- STEP 2 of 2 — configure the project database.
--
-- RUN THIS IN: pgAdmin Query Tool, RECONNECTED to the "adw_dev" database,
--              still using your admin connection.
--
-- pgAdmin cannot switch databases mid-script, which is why this is a separate
-- file. Open a new Query Tool tab against adw_dev before running it.
-- ===========================================================================


-- --- 2a. Refuse to run against the wrong database. -----------------------
-- Guards against accidentally applying this to another project's database.
DO $$
BEGIN
    IF current_database() <> 'adw_dev' THEN
        RAISE EXCEPTION
            'Connected to "%", expected "adw_dev". Reconnect before running this script.',
            current_database();
    END IF;
END
$$;


-- --- 2b. Remove blanket create rights on the public schema. --------------
-- PostgreSQL 15 and later already withhold CREATE on public from PUBLIC, so
-- this is usually a no-op. It is stated explicitly so the grant model is
-- deliberate rather than inherited, and so the same script is correct if the
-- cluster was upgraded from an older major version.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- adw_owner owns the database and therefore the public schema through
-- pg_database_owner, but the grant is made explicit for the same reason.
GRANT USAGE, CREATE ON SCHEMA public TO adw_owner;


-- --- 2c. Verify. ---------------------------------------------------------
SELECT
    current_database()                            AS database,
    n.nspname                                     AS schema,
    pg_catalog.pg_get_userbyid(n.nspowner)        AS schema_owner,
    has_schema_privilege('adw_owner', 'public', 'CREATE') AS owner_can_create,
    has_schema_privilege('public',    'public', 'CREATE') AS public_can_create
FROM pg_namespace n
WHERE n.nspname = 'public';

-- Expected: owner_can_create = true, public_can_create = false.


-- ===========================================================================
-- NOT created here, deliberately.
--
-- The runtime application role (adw_app), the anchoring role (adw_anchor), and
-- the read-only auditor role (adw_auditor) belong to Phase 1 Task 3, which owns
-- the row-level-security foundation. D18/G3 require the runtime role to be a
-- non-owner without BYPASSRLS, so it must not be adw_owner.
--
-- Task 3 will need your admin connection again, because creating roles requires
-- privileges adw_owner intentionally does not have.
-- ===========================================================================
