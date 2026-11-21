"""Configuration errors exposed across storage and application boundaries."""

from __future__ import annotations


class ConfigConflictError(ValueError):
    """The saved configuration changed after an editor or transaction read it."""
