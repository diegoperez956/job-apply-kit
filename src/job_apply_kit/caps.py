"""Daily and per-company application caps.

A cap of zero is a config error, not a way to say "don't apply anywhere" --
if you want the tool to do nothing, don't run it. Encoding "off" as zero
just invites an off-by-one where the cap silently becomes "no limit"
somewhere downstream. Unset the cap / don't invoke the applier instead.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CapConfigError(ValueError):
    """A caps config value is invalid (missing, zero, negative, or an
    unknown timezone)."""


class CapExceededError(RuntimeError):
    """record()/reserve() was called after the cap for that scope was
    already hit."""


@dataclass
class CapsConfig:
    daily_cap: int
    per_company_cap: int
    tz: str = "UTC"  # IANA zone name; governs the daily-cap day boundary

    def __post_init__(self) -> None:
        if self.daily_cap <= 0:
            raise CapConfigError(f"daily_cap must be > 0, got {self.daily_cap}")
        if self.per_company_cap <= 0:
            raise CapConfigError(f"per_company_cap must be > 0, got {self.per_company_cap}")
        try:
            ZoneInfo(self.tz)
        except ZoneInfoNotFoundError as e:
            raise CapConfigError(f"tz={self.tz!r} is not a known IANA timezone") from e


def load_caps_from_env(env: Mapping[str, str] | None = None) -> CapsConfig:
    """Read JOB_APPLY_DAILY_CAP / JOB_APPLY_PER_COMPANY_CAP / JOB_APPLY_TZ
    (see .env.example). Missing or non-integer cap values raise
    CapConfigError -- there is no silent default, a cap you never set is a
    cap you didn't mean to enforce. JOB_APPLY_TZ defaults to UTC."""
    env = env if env is not None else os.environ

    def _read_int(key: str) -> int:
        raw = env.get(key)
        if raw is None or not raw.strip():
            raise CapConfigError(f"{key} is not set")
        try:
            return int(raw)
        except ValueError as e:
            raise CapConfigError(f"{key}={raw!r} is not an integer") from e

    return CapsConfig(
        daily_cap=_read_int("JOB_APPLY_DAILY_CAP"),
        per_company_cap=_read_int("JOB_APPLY_PER_COMPANY_CAP"),
        tz=(env.get("JOB_APPLY_TZ") or "UTC").strip() or "UTC",
    )


_COMPANY_SUFFIX_RE = re.compile(
    r"\b(incorporated|inc|l\.l\.c|llc|corporation|corp|company|co|limited|ltd|plc)\.?\s*$",
    re.IGNORECASE,
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_company(name: str) -> str:
    """Fold a company name to a stable ledger key: lowercase, strip a
    trailing legal-entity suffix (Inc/LLC/Corp/Ltd/...), then collapse all
    non-alphanumerics. "Acme, Inc." and "ACME INC" both normalize to
    "acme".

    ponytail: this is a heuristic, not a company registry -- two
    genuinely different names that only differ by punctuation/case/legal
    suffix will collide (rare for job-search purposes). Swap in a real
    entity-resolution step if that ever matters more than staying simple.
    """
    lowered = name.strip().lower()
    lowered = _COMPANY_SUFFIX_RE.sub("", lowered).strip()
    return _NON_ALNUM_RE.sub("", lowered)


DEFAULT_DB_PATH = Path("data/caps.sqlite3")


class CapsLedger:
    """Durable, cross-process record of applications submitted, enforcing
    daily (timezone-aware) and per-company-7d caps.

    Backed by SQLite: `reserve()` runs its check-then-insert inside one
    BEGIN IMMEDIATE transaction, so SQLite's own file locking -- not a
    hand-rolled lock file -- makes two processes racing to reserve the
    same slot serialize correctly instead of interleaving.

    Takes the whole `CapsConfig` at construction, not a separate `tz`
    string -- there was previously nothing stopping a caller from
    constructing the ledger with one timezone and then reserving against
    a config carrying a different one, so the day boundary silently used
    whichever tz the ledger happened to be built with instead of the
    config's. One object owns the tz now; reserve()/status() read it from
    self.config, not from a second argument.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH, *, config: CapsConfig) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = config
        self.tz = ZoneInfo(config.tz)  # already validated by CapsConfig.__post_init__
        # isolation_level=None => autocommit; we drive transactions
        # explicitly (BEGIN IMMEDIATE) in reserve() for atomicity.
        self._conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS applications ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "company TEXT NOT NULL, "
            "ts_utc TEXT NOT NULL)"
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> CapsLedger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _normalize_now(self, now: datetime | None) -> datetime:
        """Resolve the `now` argument all public methods take: default to
        the current UTC instant, and normalize any caller-supplied value
        to UTC. Naive datetimes are rejected outright -- astimezone()
        silently assumes the system local zone for a naive datetime,
        which would make the day-boundary and stored timestamps depend
        on whatever machine happens to run this, so we refuse to guess.
        Normalizing here (not just at insert) also keeps every ts_utc
        comparison string on the same "+00:00" offset -- ISO8601 strings
        with different UTC offsets don't sort correctly as plain text,
        which is exactly what `ts_utc >= ? AND ts_utc < ?` relies on.
        """
        if now is None:
            return datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("naive datetime not allowed -- pass a tz-aware datetime")
        return now.astimezone(timezone.utc)

    def _day_bounds_utc(self, now: datetime) -> tuple[str, str]:
        local = now.astimezone(self.tz)
        start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        return (
            start_local.astimezone(timezone.utc).isoformat(),
            end_local.astimezone(timezone.utc).isoformat(),
        )

    def count_today(self, *, now: datetime | None = None) -> int:
        now = self._normalize_now(now)
        start, end = self._day_bounds_utc(now)
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM applications WHERE ts_utc >= ? AND ts_utc < ?", (start, end)
        )
        return cur.fetchone()[0]

    def count_company_7d(self, company: str, *, now: datetime | None = None) -> int:
        now = self._normalize_now(now)
        since = (now - timedelta(days=7)).isoformat()
        key = normalize_company(company)
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM applications WHERE company = ? AND ts_utc >= ?", (key, since)
        )
        return cur.fetchone()[0]

    def reserve(self, company: str, *, now: datetime | None = None) -> None:
        """Atomically check both caps (from self.config) and record one
        application for `company`, or raise CapExceededError and record
        nothing."""
        now = self._normalize_now(now)
        key = normalize_company(company)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            if self.count_today(now=now) >= self.config.daily_cap:
                raise CapExceededError(f"daily cap ({self.config.daily_cap}) already reached")
            if self.count_company_7d(company, now=now) >= self.config.per_company_cap:
                raise CapExceededError(
                    f"7-day cap for {key!r} ({self.config.per_company_cap}) already reached"
                )
            self._conn.execute(
                "INSERT INTO applications (company, ts_utc) VALUES (?, ?)", (key, now.isoformat())
            )
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    def status(self, companies: list[str] | None = None) -> dict:
        """Snapshot of current usage against self.config, for `caps status`."""
        used_today = self.count_today()
        out: dict = {
            "tz": str(self.tz),
            "daily_used": used_today,
            "daily_cap": self.config.daily_cap,
            "daily_remaining": max(0, self.config.daily_cap - used_today),
        }
        if companies:
            out["companies"] = {}
            for c in companies:
                used = self.count_company_7d(c)
                out["companies"][normalize_company(c)] = {
                    "used_7d": used,
                    "cap": self.config.per_company_cap,
                    "remaining": max(0, self.config.per_company_cap - used),
                }
        return out
