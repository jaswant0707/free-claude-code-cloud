"""Supabase persistence client for Free Claude Code Cloud.

Interacts with Supabase PostgREST RPC endpoints to persist and load:
- Encrypted provider API keys
- Application settings
- Code sessions and cloud workspace metadata
- Security and audit events
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Final
from loguru import logger
import httpx

from .crypto import _DEFAULT_ANON_KEY, decrypt_secret, encrypt_secret, mask_secret

# Default Supabase configuration for FCC Cloud
_DEFAULT_SUPABASE_URL: Final[str] = "https://emlenqcewhlwtnigwkac.supabase.co"


class SupabaseClient:
    """Client for managing FCC persistence via Supabase."""

    def __init__(
        self,
        base_url: str | None = None,
        anon_key: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        url = (
            base_url
            or os.getenv("SUPABASE_URL", "").strip()
            or _DEFAULT_SUPABASE_URL
        )
        self.base_url = url.rstrip("/")
        service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        self.anon_key = (
            service_role_key
            or anon_key
            or os.getenv("SUPABASE_ANON_KEY", "").strip()
            or os.getenv("SUPABASE_KEY", "").strip()
            or _DEFAULT_ANON_KEY
        )
        self.timeout = timeout
        self.rpc_url = f"{self.base_url}/rest/v1/rpc"
        self._limits = httpx.Limits(
            max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0
        )
        self._sync_client: httpx.Client | None = None
        self._async_client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.anon_key)

    def _get_sync_client(self) -> httpx.Client:
        if self._sync_client is None or self._sync_client.is_closed:
            self._sync_client = httpx.Client(timeout=self.timeout, limits=self._limits)
        return self._sync_client

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None or self._async_client.is_closed:
            self._async_client = httpx.AsyncClient(timeout=self.timeout, limits=self._limits)
        return self._async_client

    def close(self) -> None:
        if self._sync_client and not self._sync_client.is_closed:
            self._sync_client.close()

    async def aclose(self) -> None:
        if self._async_client and not self._async_client.is_closed:
            await self._async_client.aclose()

    def _headers(self) -> dict[str, str]:
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        server_token = os.getenv("FCC_SERVER_TOKEN", "").strip()
        if not server_token:
            enc_key = os.getenv("FCC_ENCRYPTION_KEY", "").strip()
            salt = enc_key or "fcc-backend-authorization-seed-2026"
            server_token = hashlib.sha256(f"fcc-server-token:{salt}".encode("utf-8")).hexdigest()
        headers["x-fcc-server-token"] = server_token
        return headers

    def _rpc(self, function_name: str, payload: dict[str, Any] | None = None) -> Any:
        """Call a Supabase PostgreSQL stored function via PostgREST RPC synchronously."""
        if not self.is_configured:
            return None
        url = f"{self.rpc_url}/{function_name}"
        try:
            client = self._get_sync_client()
            resp = client.post(
                url,
                headers=self._headers(),
                json=payload or {},
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Supabase RPC {} failed with status {}: {}",
                    function_name,
                    resp.status_code,
                    resp.text,
                )
                return None
            return resp.json()
        except Exception as exc:
            logger.warning("Supabase RPC {} error: {}", function_name, exc)
            return None

    async def _rpc_async(
        self, function_name: str, payload: dict[str, Any] | None = None
    ) -> Any:
        """Call a Supabase PostgreSQL stored function via PostgREST RPC asynchronously."""
        if not self.is_configured:
            return None
        url = f"{self.rpc_url}/{function_name}"
        try:
            client = self._get_async_client()
            resp = await client.post(
                url,
                headers=self._headers(),
                json=payload or {},
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Supabase async RPC {} failed with status {}: {}",
                    function_name,
                    resp.status_code,
                    resp.text,
                )
                return None
            return resp.json()
        except Exception as exc:
            logger.warning("Supabase async RPC {} error: {}", function_name, exc)
            return None

    # --------------------------------------------------------------------------
    # Provider Configurations
    # --------------------------------------------------------------------------

    def upsert_provider_config(
        self,
        provider_id: str,
        provider_name: str,
        raw_api_key: str | None = None,
        is_active: bool = True,
        is_default: bool = False,
        priority: int = 0,
        default_model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Save encrypted provider credentials and configuration."""
        encrypted_key = encrypt_secret(raw_api_key) if raw_api_key else None
        key_mask = mask_secret(raw_api_key) if raw_api_key else None

        payload = {
            "p_provider_id": provider_id,
            "p_provider_name": provider_name,
            "p_encrypted_api_key": encrypted_key,
            "p_key_mask": key_mask,
            "p_is_active": is_active,
            "p_is_default": is_default,
            "p_priority": priority,
            "p_default_model": default_model,
            "p_metadata": metadata or {},
        }
        return self._rpc("fcc_upsert_provider_config", payload)

    def list_provider_configs(self, decrypt: bool = False) -> list[dict[str, Any]]:
        """List provider configurations. Decrypts credentials only if decrypt=True."""
        rows = self._rpc("fcc_list_provider_configs", {}) or []
        results = []
        for row in rows:
            item = dict(row)
            enc_key = item.get("encrypted_api_key")
            if decrypt and enc_key:
                try:
                    item["api_key"] = decrypt_secret(enc_key)
                except Exception as exc:
                    logger.warning(
                        "Could not decrypt provider {} key: {}",
                        item.get("provider_id"),
                        exc,
                    )
                    item["api_key"] = None
            else:
                item["api_key"] = None

            # Always remove encrypted_api_key from public view
            if not decrypt:
                item.pop("encrypted_api_key", None)
            results.append(item)
        return results

    def delete_provider_config(self, provider_id: str) -> bool:
        """Delete a provider configuration from database."""
        result = self._rpc("fcc_delete_provider_config", {"p_provider_id": provider_id})
        return bool(result)

    # --------------------------------------------------------------------------
    # Application Settings
    # --------------------------------------------------------------------------

    def upsert_app_setting(
        self,
        key: str,
        value: str,
        is_secret: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Store an application setting."""
        val = encrypt_secret(value) if is_secret else value
        payload = {
            "p_key": key,
            "p_value": val,
            "p_is_secret": is_secret,
            "p_metadata": metadata or {},
        }
        return self._rpc("fcc_upsert_app_setting", payload)

    def get_app_settings(self) -> dict[str, str]:
        """Fetch all persistent application settings."""
        res = self._rpc("fcc_get_app_settings", {})
        if not res:
            return {}
        if isinstance(res, dict):
            return res
        settings: dict[str, str] = {}
        for row in res:
            if isinstance(row, dict):
                k = row.get("key")
                v = row.get("value")
                is_sec = row.get("is_secret", False)
                if k and v:
                    if is_sec:
                        try:
                            settings[k] = decrypt_secret(v)
                        except Exception:
                            settings[k] = v
                    else:
                        settings[k] = v
        return settings

    # --------------------------------------------------------------------------
    # Code Sessions
    # --------------------------------------------------------------------------

    def upsert_code_session(
        self,
        session_id: str,
        owner_email: str,
        title: str,
        repo_url: str | None = None,
        workspace_dir: str = "",
        provider_id: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        status: str = "ready",
        harness: str = "codex",
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Create or update a cloud Code session."""
        payload = {
            "p_id": session_id,
            "p_owner_email": owner_email,
            "p_title": title,
            "p_repo_url": repo_url,
            "p_workspace_dir": workspace_dir,
            "p_provider_id": provider_id,
            "p_model": model,
            "p_reasoning_effort": reasoning_effort,
            "p_status": status,
            "p_harness": harness,
            "p_error": error,
            "p_metadata": metadata or {},
        }
        return self._rpc("fcc_upsert_code_session", payload)

    def list_code_sessions(self, owner_email: str) -> list[dict[str, Any]]:
        """List all code sessions belonging to the owner."""
        return self._rpc("fcc_list_code_sessions", {"p_owner_email": owner_email}) or []

    def delete_code_session(self, session_id: str, owner_email: str) -> bool:
        """Delete a code session."""
        result = self._rpc(
            "fcc_delete_code_session",
            {"p_id": session_id, "p_owner_email": owner_email},
        )
        return bool(result)

    def upsert_code_run(
        self,
        session_id: str,
        run_id: str,
        command: str,
        status: str,
        output: str | None = None,
        error: str | None = None,
        exit_code: int | None = None,
        duration: float | None = None,
        finished_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Upsert a code run for background execution tracking and status persistence."""
        payload = {
            "p_session_id": session_id,
            "p_id": run_id,
            "p_command": command,
            "p_status": status,
            "p_output": output,
            "p_error": error,
            "p_exit_code": exit_code,
            "p_duration": duration,
            "p_finished_at": finished_at,
        }
        return self._rpc("fcc_upsert_code_run", payload)

    def get_code_run(self, session_id: str, run_id: str) -> dict[str, Any] | None:
        """Retrieve persisted code run state, output, and completion status."""
        return self._rpc("fcc_get_code_run", {"p_session_id": session_id, "p_id": run_id})

    def list_code_runs(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """List code runs for a session in descending ordinal order."""
        return self._rpc("fcc_list_code_runs", {"p_session_id": session_id, "p_limit": limit}) or []

    # --------------------------------------------------------------------------
    # Audit Events
    # --------------------------------------------------------------------------

    def record_audit_event(
        self,
        event_type: str,
        actor_email: str | None = None,
        ip_address: str | None = None,
        status: str = "success",
        details: dict[str, Any] | None = None,
    ) -> str | None:
        """Record an operational or security audit event."""
        payload = {
            "p_event_type": event_type,
            "p_actor_email": actor_email,
            "p_ip_address": ip_address,
            "p_status": status,
            "p_details": details or {},
        }
        return self._rpc("fcc_record_audit_event", payload)

    # --------------------------------------------------------------------------
    # Universal API Keys
    # --------------------------------------------------------------------------

    def create_universal_key(
        self,
        name: str,
        key_prefix: str,
        key_hash: str,
        default_model: str | None = None,
        fallback_models: list[str] | None = None,
        rate_limit_rpm: int = 60,
        expires_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Create a new universal API key record."""
        payload = {
            "p_name": name,
            "p_key_prefix": key_prefix,
            "p_key_hash": key_hash,
            "p_default_model": default_model,
            "p_fallback_models": fallback_models or [],
            "p_rate_limit_rpm": rate_limit_rpm,
            "p_expires_at": expires_at,
        }
        return self._rpc("fcc_create_universal_key", payload)

    def list_universal_keys(self) -> list[dict[str, Any]]:
        """List all universal API keys."""
        return self._rpc("fcc_list_universal_keys", {}) or []

    def verify_universal_key(self, key_hash: str) -> dict[str, Any] | None:
        """Atomically verify a universal key hash and increment usage."""
        return self._rpc("fcc_verify_universal_key", {"p_key_hash": key_hash})

    def toggle_universal_key(self, key_id: str, is_active: bool) -> bool:
        """Toggle active/revoked status of a universal API key."""
        return bool(self._rpc("fcc_toggle_universal_key", {"p_key_id": key_id, "p_is_active": is_active}))

    def delete_universal_key(self, key_id: str) -> bool:
        """Permanently delete a universal API key."""
        result = self._rpc("fcc_delete_universal_key", {"p_key_id": key_id})
        if result is True:
            return True
        # Verify if key is successfully absent (handles PL/pgSQL FOUND behavior with dynamic SQL)
        remaining = [k for k in self.list_universal_keys() if str(k.get("id")) == str(key_id)]
        return len(remaining) == 0

    # --------------------------------------------------------------------------
    # Model Test Playground
    # --------------------------------------------------------------------------

    def upsert_model_test_session(
        self,
        session_id: str,
        title: str,
        selected_model: str = "auto",
        provider_hint: str | None = None,
    ) -> dict[str, Any] | None:
        """Create or update a model test playground session."""
        payload = {
            "p_id": session_id,
            "p_title": title,
            "p_selected_model": selected_model,
            "p_provider_hint": provider_hint,
        }
        return self._rpc("fcc_upsert_model_test_session", payload)

    def list_model_test_sessions(self) -> list[dict[str, Any]]:
        """List all model test playground sessions."""
        return self._rpc("fcc_list_model_test_sessions", {}) or []

    def get_model_test_session(self, session_id: str) -> dict[str, Any] | None:
        """Fetch a model test session with all historical messages."""
        return self._rpc("fcc_get_model_test_session", {"p_id": session_id})

    def delete_model_test_session(self, session_id: str) -> bool:
        """Delete a model test playground session and its messages."""
        return bool(self._rpc("fcc_delete_model_test_session", {"p_id": session_id}))

    def add_model_test_message(
        self,
        session_id: str,
        role: str,
        content: str,
        resolved_provider: str | None = None,
        resolved_model: str | None = None,
        latency_ms: int | None = None,
        tokens_used: int | None = None,
        error_detail: str | None = None,
    ) -> dict[str, Any] | None:
        """Record a chat message in a model test playground session."""
        payload = {
            "p_session_id": session_id,
            "p_role": role,
            "p_content": content,
            "p_resolved_provider": resolved_provider,
            "p_resolved_model": resolved_model,
            "p_latency_ms": latency_ms,
            "p_tokens_used": tokens_used,
            "p_error_detail": error_detail,
        }
        return self._rpc("fcc_add_model_test_message", payload)


# Singleton instance
_supabase_instance: SupabaseClient | None = None


def get_supabase_client() -> SupabaseClient:
    """Return the global SupabaseClient singleton."""
    global _supabase_instance
    if _supabase_instance is None:
        _supabase_instance = SupabaseClient()
    return _supabase_instance
