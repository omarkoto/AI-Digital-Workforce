-- ===========================================================================
-- STEP 1 of 2 — create the application role and the project database.
--
-- RUN THIS IN: pgAdmin Query Tool, connected to PostgreSQL 18, against the
--              "postgres" maintenance database, using your admin connection.
--
-- Plain SQL only. No psql meta-commands, so it runs unmodified in pgAdmin.
--
-- SAFETY: creates only new objects named adw_owner / adw_dev. It never
-- references bankchatbot, mortgagedb, smart_car_qr, or any other database.
--
-- NOTE: pgAdmin's Query Tool runs in autocommit by default. CREATE DATABASE
-- cannot run inside a transaction block, so leave autocommit ON.
-- ===========================================================================


-- --- 1a. Pre-flight. Confirms adw_dev does not exist and shows that the
--         databases you asked to protect are untouched by this script. -------
SELECT datname AS existing_database
FROM pg_database
WHERE datname IN ('adw_dev', 'bankchatbot', 'mortgagedb', 'smart_car_qr')
ORDER BY datname;


-- --- 1b. Create the owner role, without a password. ----------------------
-- Idempotent: safe to run twice.
--
-- The password is deliberately NOT set here so it never enters your pgAdmin
-- query history. Set it in step 1c.
--
-- This role is intentionally minimal: it can log in and own its database, and
-- nothing more. It is NOT a superuser.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'adw_owner') THEN
        CREATE ROLE adw_owner WITH
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT
            NOREPLICATION
            NOBYPASSRLS;
        RAISE NOTICE 'Created role adw_owner (no password yet).';
    ELSE
        RAISE NOTICE 'Role adw_owner already exists; left unchanged.';
    END IF;
END
$$;


-- --- 1c. Set the password for adw_owner. ---------------------------------
-- PREFERRED: skip this statement and set the password through the pgAdmin UI
--   Object Explorer -> Login/Group Roles -> adw_owner
--   -> Properties -> Definition -> Password -> Save
-- That keeps the password out of your query history.
--
-- If you prefer SQL, uncomment the line below, replace the placeholder, run
-- it, then clear the Query Tool history.
--
-- ALTER ROLE adw_owner WITH PASSWORD 'REPLACE_WITH_A_LOCAL_PASSWORD';


-- --- 1d. Create the database owned by adw_owner. -------------------------
-- Not idempotent: PostgreSQL has no CREATE DATABASE IF NOT EXISTS, and it
-- cannot be wrapped in a DO block. If it reports 'database "adw_dev" already
-- exists', that is fine — move on to step 2.
CREATE DATABASE adw_dev WITH OWNER = adw_owner;


-- --- 1e. Verify. ---------------------------------------------------------
SELECT
    d.datname                         AS database,
    pg_catalog.pg_get_userbyid(d.datdba) AS owner,
    pg_catalog.pg_encoding_to_char(d.encoding) AS encoding,
    r.rolcanlogin                     AS owner_can_login,
    r.rolsuper                        AS owner_is_superuser,
    r.rolbypassrls                    AS owner_bypasses_rls
FROM pg_database d
JOIN pg_roles r ON r.rolname = 'adw_owner'
WHERE d.datname = 'adw_dev';

-- Expected: owner = adw_owner, encoding = UTF8,
--           owner_can_login = true, owner_is_superuser = false,
--           owner_bypasses_rls = false.
--
-- If encoding is not UTF8, stop and tell me — the database should be recreated
-- with an explicit UTF8 encoding before any schema is applied.
