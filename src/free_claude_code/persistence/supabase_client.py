"""Supabase persistence client for Free Claude Code Cloud.

Interacts with Supabase PostgREST RPC endpoints to persist and load:
- Encrypted provider API keys
- Application settings
- Code sessions and cloud workspace metadata
- Security and audit events
"""

from __future__ import annotations

import os
from typing import Any, Final
from loguru import logger
import httpx

from .crypto import decrypt_secret, encrypt_secret, mask_secret

# Default Supabase configuration for FCC Cloud
_DEFAULT_SUPABASE_URL: Final[str] = "https://emlenqcewhlwtnigwkac.supabase.co"
_DEFAULT_ANON_KEY: Final[str] = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVtbGVucWNld2hsd3RuaWd3a2FjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTUzNTI4MjIsImV4cCI6MjExMDkyODgyMn0."
    "qZz-V-6TpUrfrH9OTOA53GLWRekHgGIop1TcA3EOLz8"
)


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
        self.anon_key = (
            anon_key
            or os.getenv("SUPABASE_ANON_KEY", "").strip()
            or os.getenv("SUPABASE_KEY", "").strip()
            or _DEFAULT_ANON_KEY
        )
        self.timeout = timeout
        self.rpc_url = f"{self.base_url}/rest/v1/rpc"

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.anon_key)

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {self.anon_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _rpc(self, function_name: str, payload: dict[str, Any] | None = None) -> Any:
        """Call a Supabase PostgreSQL stored function via PostgREST RPC synchronously."""
        if not self.is_configured:
            return None
        url = f"{self.rpc_url}/{function_name}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
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
            async with httpx.AsyncClient(timeout=self.timeout) as client:
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
        rows = self._rpc("fcc_get_app_settings", {}) or []
        settings: dict[str, str] = {}
        for row in rows:
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


# Singleton instance
_supabase_instance: SupabaseClient | None = None


def get_supabase_client() -> SupabaseClient:
    """Return the global SupabaseClient singleton."""
    global _supabase_instance
    if _supabase_instance is None:
        _supabase_instance = SupabaseClient()
    return _supabase_instance
