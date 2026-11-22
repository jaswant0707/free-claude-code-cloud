-- ==============================================================================
-- Migration: 20261123_harden_security_definer_grants.sql
-- Description: Hardens execution privileges on all 28 SECURITY DEFINER functions.
--              Revokes EXECUTE from PUBLIC, anon, and authenticated roles.
--              Restricts EXECUTE strictly to service_role and postgres backend roles.
--              Resolves Supabase Security Advisor lint warning:
--              "28 SECURITY DEFINER functions executable by anon/authenticated roles".
-- ==============================================================================

DO $$
DECLARE
    r RECORD;
    func_signature text;
BEGIN
    FOR r IN
        SELECT 
            p.oid,
            p.proname,
            pg_get_function_identity_arguments(p.oid) AS args
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'public'
          AND p.proname LIKE 'fcc_%'
          AND p.prosecdef = true
    LOOP
        func_signature := 'public.' || quote_ident(r.proname) || '(' || r.args || ')';
        
        -- Revoke execution from untrusted client roles
        EXECUTE 'REVOKE EXECUTE ON FUNCTION ' || func_signature || ' FROM PUBLIC, anon, authenticated CASCADE;';
        
        -- Grant execution exclusively to trusted backend service_role and postgres admin
        EXECUTE 'GRANT EXECUTE ON FUNCTION ' || func_signature || ' TO service_role, postgres;';
        
        RAISE NOTICE 'Hardened privileges for %', func_signature;
    END LOOP;
END;
$$;
