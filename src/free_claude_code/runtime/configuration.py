"""Worker boundary for managed configuration; runtime state stays on the loop."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from secrets import token_bytes

from anyio import CapacityLimiter, to_thread

from free_claude_code.config.admin.custom_providers import CustomProviderMutation
from free_claude_code.config.admin.persistence import (
    PreparedAdminUpdate,
    prepare_admin_update,
)
from free_claude_code.config.admin.state import ConfigInputValue, ValueState
from free_claude_code.config.admin.values import load_config_response, load_value_state
from free_claude_code.config.loader import ManagedConfigStore
from free_claude_code.config.settings import Settings
from free_claude_code.core.json_types import JsonObject


class ConfigurationService:
    def __init__(
        self,
        store: ManagedConfigStore,
        revision_key: bytes | None = None,
    ) -> None:
        self._store = store
        self._revision_key = (
            revision_key if revision_key is not None else self._resolve_revision_key()
        )
        # Storage is serialized; its waiters must not exhaust FastAPI's worker pool.
        self._worker_limiter = CapacityLimiter(1)

    @staticmethod
    def _resolve_revision_key() -> bytes:
        key_env = os.getenv("FCC_REVISION_KEY", "").strip()
        if key_env:
            return hashlib.sha256(key_env.encode("utf-8")).digest()

        is_cloud = bool(
            os.getenv("FCC_CLOUD_DEPLOYMENT")
            or os.getenv("VERCEL")
            or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
        )
        owner_pw = os.getenv("OWNER_PASSWORD", "").strip()
        admin_token = os.getenv("ADMIN_AUTH_TOKEN", "").strip()
        master_token = os.getenv("MASTER_API_TOKEN", "").strip()
        anthropic_token = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()

        if is_cloud or owner_pw or admin_token or master_token or anthropic_token:
            seed = (
                f"fcc-revision-key-v1:{owner_pw}:{admin_token}:{master_token}:"
                f"{anthropic_token}:{os.getenv('VERCEL_PROJECT_ID', '')}"
            )
            return hashlib.sha256(seed.encode("utf-8")).digest()

        return token_bytes(32)

    async def initialize(self) -> None:
        await to_thread.run_sync(self._store.initialize, limiter=self._worker_limiter)

    async def admin_config(self) -> JsonObject:
        snapshot = await to_thread.run_sync(
            self._store.read, limiter=self._worker_limiter
        )
        return load_config_response(snapshot, revision_key=self._revision_key)

    async def admin_values(self) -> ValueState:
        snapshot = await to_thread.run_sync(
            self._store.read, limiter=self._worker_limiter
        )
        return load_value_state(snapshot)

    async def prepare(
        self,
        updates: Mapping[str, ConfigInputValue],
        active_settings: Settings,
        custom_provider: CustomProviderMutation | None = None,
    ) -> PreparedAdminUpdate:
        snapshot = await to_thread.run_sync(
            self._store.read, limiter=self._worker_limiter
        )
        return prepare_admin_update(
            updates,
            snapshot,
            active_settings,
            custom_provider,
            revision_key=self._revision_key,
        )

    async def commit(self, prepared: PreparedAdminUpdate) -> JsonObject:
        if not prepared.valid:
            raise ValueError("Cannot commit an invalid Admin update")
        await to_thread.run_sync(
            self._store.commit,
            prepared.target_values,
            prepared.expected,
            limiter=self._worker_limiter,
        )
        return prepared.applied_response()
