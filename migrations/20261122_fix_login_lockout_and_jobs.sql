-- ==============================================================================
-- Migration: 20261122_fix_login_lockout_and_jobs.sql
-- Description:
--   1. Auto-resets expired lockouts and clears failed_login_attempts in fcc_get_owner_account.
--   2. Ensures fcc_update_owner_login starts fresh attempt counter after lockout expires.
--   3. Adds fcc_upsert_code_run, fcc_get_code_run, and fcc_list_code_runs for durable
--      serverless background-job execution and status recovery.
-- ==============================================================================

ALTER TABLE public.fcc_code_runs ADD COLUMN IF NOT EXISTS exit_code integer;
ALTER TABLE public.fcc_code_runs ADD COLUMN IF NOT EXISTS duration double precision;
ALTER TABLE public.fcc_code_runs ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT NOW();

CREATE OR REPLACE FUNCTION public.fcc_get_owner_account(p_email text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_result JSONB;
    v_record public.fcc_owner_accounts%ROWTYPE;
BEGIN
    IF NOT public.fcc_verify_backend_caller() THEN
        RAISE EXCEPTION 'Access denied: unauthorized RPC execution' USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_record
    FROM public.fcc_owner_accounts
    WHERE email = LOWER(TRIM(p_email));

    IF FOUND THEN
        -- If an account was previously locked but the lockout period has now elapsed,
        -- clear the expired lockout and reset attempts so legitimate owner can log in normally.
        IF v_record.locked_until IS NOT NULL AND NOW() > v_record.locked_until THEN
            UPDATE public.fcc_owner_accounts
            SET locked_until = NULL,
                failed_login_attempts = 0,
                updated_at = NOW()
            WHERE email = LOWER(TRIM(p_email));

            SELECT * INTO v_record
            FROM public.fcc_owner_accounts
            WHERE email = LOWER(TRIM(p_email));
        END IF;

        v_result := to_jsonb(v_record);
    END IF;

    RETURN v_result;
END;
$$;

CREATE OR REPLACE FUNCTION public.fcc_update_owner_login(
    p_email text,
    p_success boolean
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_result JSONB;
    v_now timestamptz := NOW();
    v_record public.fcc_owner_accounts%ROWTYPE;
    v_attempts integer;
BEGIN
    IF NOT public.fcc_verify_backend_caller() THEN
        RAISE EXCEPTION 'Access denied: unauthorized RPC execution' USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_record
    FROM public.fcc_owner_accounts
    WHERE email = LOWER(TRIM(p_email));

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    IF p_success THEN
        UPDATE public.fcc_owner_accounts
        SET failed_login_attempts = 0,
            locked_until = NULL,
            last_login_at = v_now,
            updated_at = v_now
        WHERE email = LOWER(TRIM(p_email));
    ELSE
        -- If previous lockout has expired, start a fresh attempt counter
        IF v_record.locked_until IS NOT NULL AND v_now > v_record.locked_until THEN
            v_attempts := 1;
        ELSE
            v_attempts := COALESCE(v_record.failed_login_attempts, 0) + 1;
        END IF;

        UPDATE public.fcc_owner_accounts
        SET failed_login_attempts = v_attempts,
            locked_until = CASE WHEN v_attempts >= 5 THEN v_now + INTERVAL '15 minutes' ELSE NULL END,
            updated_at = v_now
        WHERE email = LOWER(TRIM(p_email));
    END IF;

    SELECT to_jsonb(t) INTO v_result FROM public.fcc_owner_accounts t WHERE t.email = LOWER(TRIM(p_email));
    RETURN v_result;
END;
$$;

CREATE OR REPLACE FUNCTION public.fcc_upsert_code_run(
    p_session_id text,
    p_id text,
    p_command text,
    p_status text,
    p_output text DEFAULT NULL,
    p_error text DEFAULT NULL,
    p_exit_code integer DEFAULT NULL,
    p_duration double precision DEFAULT NULL,
    p_finished_at timestamptz DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_result JSONB;
    v_ordinal integer;
BEGIN
    IF NOT public.fcc_verify_backend_caller() THEN
        RAISE EXCEPTION 'Access denied: unauthorized RPC execution' USING ERRCODE = '42501';
    END IF;

    -- Ensure parent session exists to prevent foreign key violation
    IF NOT EXISTS (SELECT 1 FROM public.fcc_code_sessions WHERE id = p_session_id) THEN
        INSERT INTO public.fcc_code_sessions (id, owner_email, title, workspace_dir, status, created_at, updated_at)
        VALUES (p_session_id, 'jaswanty132@gmail.com', 'Workspace Session ' || p_session_id, '/tmp/.fcc/workspaces/' || p_session_id, 'ready', NOW(), NOW())
        ON CONFLICT (id) DO NOTHING;
    END IF;

    SELECT COALESCE(MAX(ordinal), 0) + 1 INTO v_ordinal
    FROM public.fcc_code_runs
    WHERE session_id = p_session_id;

    INSERT INTO public.fcc_code_runs (
        session_id, id, ordinal, command, status, output, error, exit_code, duration, created_at, finished_at
    )
    VALUES (
        p_session_id, p_id, v_ordinal, p_command, p_status, p_output, p_error, p_exit_code, p_duration, NOW(), p_finished_at
    )
    ON CONFLICT (session_id, id) DO UPDATE
    SET status = EXCLUDED.status,
        output = COALESCE(EXCLUDED.output, public.fcc_code_runs.output),
        error = COALESCE(EXCLUDED.error, public.fcc_code_runs.error),
        exit_code = COALESCE(EXCLUDED.exit_code, public.fcc_code_runs.exit_code),
        duration = COALESCE(EXCLUDED.duration, public.fcc_code_runs.duration),
        finished_at = COALESCE(EXCLUDED.finished_at, public.fcc_code_runs.finished_at);

    SELECT to_jsonb(t) INTO v_result
    FROM public.fcc_code_runs t
    WHERE t.session_id = p_session_id AND t.id = p_id;

    RETURN v_result;
END;
$$;

CREATE OR REPLACE FUNCTION public.fcc_get_code_run(
    p_session_id text,
    p_id text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_result JSONB;
BEGIN
    IF NOT public.fcc_verify_backend_caller() THEN
        RAISE EXCEPTION 'Access denied: unauthorized RPC execution' USING ERRCODE = '42501';
    END IF;

    SELECT to_jsonb(t) INTO v_result
    FROM public.fcc_code_runs t
    WHERE t.session_id = p_session_id AND t.id = p_id;

    RETURN v_result;
END;
$$;

CREATE OR REPLACE FUNCTION public.fcc_list_code_runs(
    p_session_id text,
    p_limit integer DEFAULT 50
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_result JSONB;
BEGIN
    IF NOT public.fcc_verify_backend_caller() THEN
        RAISE EXCEPTION 'Access denied: unauthorized RPC execution' USING ERRCODE = '42501';
    END IF;

    SELECT jsonb_agg(to_jsonb(t) ORDER BY t.ordinal DESC) INTO v_result
    FROM (
        SELECT * FROM public.fcc_code_runs
        WHERE session_id = p_session_id
        ORDER BY ordinal DESC
        LIMIT p_limit
    ) t;

    RETURN COALESCE(v_result, '[]'::jsonb);
END;
$$;
