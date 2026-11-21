"""Classify raw upstream exceptions into one provider failure verdict."""

from __future__ import annotations

from .classifier import classify
from .verdict import FailureVerdict

__all__ = ["FailureVerdict", "classify"]
