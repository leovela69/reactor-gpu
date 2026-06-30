"""Quota monitoring and tracking for all GPU/API sources."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import QUOTA_LIMITS


DATA_DIR = Path(__file__).parent.parent / "data"
QUOTA_FILE = DATA_DIR / "quotas.json"


class QuotaMonitor:
    """Tracks daily/weekly/monthly quotas for each compute source."""

    def __init__(self, quota_file: Optional[Path] = None):
        self.quota_file = quota_file or QUOTA_FILE
        self.limits = QUOTA_LIMITS
        self._usage: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Load persisted quota data from disk."""
        if self.quota_file.exists():
            try:
                with open(self.quota_file, "r") as f:
                    self._usage = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._usage = {}
        self._auto_reset()

    def _save(self) -> None:
        """Persist quota data to disk."""
        self.quota_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.quota_file, "w") as f:
            json.dump(self._usage, f, indent=2)

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _auto_reset(self) -> None:
        """Auto-reset quotas that have expired their period."""
        now = self._now()
        for source, config in self.limits.items():
            if source not in self._usage:
                self._usage[source] = {"used": 0.0, "reset_at": self._next_reset(source).isoformat()}
                continue

            reset_at_str = self._usage[source].get("reset_at")
            if reset_at_str:
                try:
                    reset_at = datetime.fromisoformat(reset_at_str)
                    if now >= reset_at:
                        self._usage[source] = {
                            "used": 0.0,
                            "reset_at": self._next_reset(source).isoformat(),
                        }
                except ValueError:
                    self._usage[source] = {
                        "used": 0.0,
                        "reset_at": self._next_reset(source).isoformat(),
                    }
        self._save()

    def _next_reset(self, source: str) -> datetime:
        """Calculate the next reset time for a source."""
        now = self._now()
        period = self.limits.get(source, {}).get("type", "daily")

        if period == "daily" or period == "rate_limited":
            return now.replace(hour=0, minute=0, second=0, microsecond=0).__add__(
                __import__("datetime").timedelta(days=1)
            )
        elif period == "weekly":
            days_until_monday = (7 - now.weekday()) % 7 or 7
            return now.replace(hour=0, minute=0, second=0, microsecond=0).__add__(
                __import__("datetime").timedelta(days=days_until_monday)
            )
        elif period == "monthly":
            if now.month == 12:
                return now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            return now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            # unlimited — set far future
            return now.replace(year=now.year + 10)

    def has_quota(self, source: str) -> bool:
        """Check if a source has remaining quota."""
        config = self.limits.get(source)
        if not config:
            return False
        if config["type"] == "unlimited":
            return True

        self._auto_reset()
        usage = self._usage.get(source, {})
        used = usage.get("used", 0.0)
        limit = config["limit"]
        return used < limit

    def get_quota_percent(self, source: str) -> float:
        """Get percentage of quota remaining (0-100)."""
        config = self.limits.get(source)
        if not config:
            return 0.0
        if config["type"] == "unlimited":
            return 100.0

        self._auto_reset()
        usage = self._usage.get(source, {})
        used = usage.get("used", 0.0)
        limit = config["limit"]
        if limit <= 0:
            return 100.0
        remaining = max(0.0, limit - used)
        return (remaining / limit) * 100.0

    def record_usage(self, source: str, amount: float = 1.0) -> None:
        """Record usage for a source."""
        self._auto_reset()
        if source not in self._usage:
            self._usage[source] = {
                "used": 0.0,
                "reset_at": self._next_reset(source).isoformat(),
            }
        self._usage[source]["used"] = self._usage[source].get("used", 0.0) + amount
        self._save()

    def get_all_quotas(self) -> dict[str, dict[str, Any]]:
        """Get status of all quotas."""
        self._auto_reset()
        result = {}
        for source, config in self.limits.items():
            usage = self._usage.get(source, {})
            used = usage.get("used", 0.0)
            limit = config["limit"]
            result[source] = {
                "type": config["type"],
                "unit": config["unit"],
                "limit": limit,
                "used": used,
                "remaining": max(0, limit - used) if limit > 0 else -1,
                "percent_remaining": self.get_quota_percent(source),
                "has_quota": self.has_quota(source),
                "reset_at": usage.get("reset_at"),
            }
        return result
