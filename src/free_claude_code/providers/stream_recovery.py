"""Stream truncation that request recovery may retry."""

from __future__ import annotations

from .recovery_errors import RetryableProviderProtocolError


class TruncatedProviderStreamError(RetryableProviderProtocolError):
    """An upstream stream ended without its required terminal marker."""
