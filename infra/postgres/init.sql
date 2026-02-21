\set analyst_ro_password `printf '%s' "${ANALYST_RO_PASSWORD:-analyst-change-me}"`

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO
$$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analyst_ro') THEN
        EXECUTE format('CREATE ROLE analyst_ro LOGIN PASSWORD %L', :'analyst_ro_password');
    ELSE
        EXECUTE format('ALTER ROLE analyst_ro WITH LOGIN PASSWORD %L', :'analyst_ro_password');
    END IF;
END
$$;

DO
$$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO analyst_ro', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO analyst_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analyst_ro;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO analyst_ro;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO analyst_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO analyst_ro;
