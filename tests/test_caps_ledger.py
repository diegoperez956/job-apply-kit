from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from job_apply_kit.caps import (
    CapConfigError,
    CapExceededError,
    CapsConfig,
    CapsLedger,
    normalize_company,
)

_SRC = str(Path(__file__).parent.parent / "src")


def test_normalize_company_folds_legal_suffixes_and_case():
    assert normalize_company("Acme, Inc.") == "acme"
    assert normalize_company("ACME INC") == "acme"
    assert normalize_company("Acme LLC") == "acme"
    assert normalize_company("  Acme Corp  ") == "acme"
    assert normalize_company("Acme, Inc.") == normalize_company("ACME INC")


def test_normalize_company_distinct_names_stay_distinct():
    assert normalize_company("Acme") != normalize_company("Acme Robotics")


def test_caps_config_rejects_unknown_timezone():
    with pytest.raises(CapConfigError):
        CapsConfig(daily_cap=1, per_company_cap=1, tz="Not/AZone")


def test_reserve_persists_and_enforces_daily_cap(tmp_path):
    db = tmp_path / "caps.sqlite3"
    config = CapsConfig(daily_cap=1, per_company_cap=5)
    with CapsLedger(db, config=config) as ledger:
        ledger.reserve("Acme")
        with pytest.raises(CapExceededError):
            ledger.reserve("OtherCo")

    # reopening the same db file sees the same count -- durability.
    with CapsLedger(db, config=config) as ledger:
        assert ledger.count_today() == 1


def test_reserve_enforces_per_company_7d_cap_keyed_on_normalized_name(tmp_path):
    db = tmp_path / "caps.sqlite3"
    config = CapsConfig(daily_cap=10, per_company_cap=1)
    with CapsLedger(db, config=config) as ledger:
        ledger.reserve("Acme Inc.")
        with pytest.raises(CapExceededError):
            ledger.reserve("ACME INC")  # normalizes to the same key
        ledger.reserve("Other Co")  # different company, unaffected
        assert ledger.count_company_7d("acme") == 1


def test_reserve_failure_records_nothing(tmp_path):
    db = tmp_path / "caps.sqlite3"
    config = CapsConfig(daily_cap=1, per_company_cap=1)
    with CapsLedger(db, config=config) as ledger:
        ledger.reserve("Acme")
        with pytest.raises(CapExceededError):
            ledger.reserve("Acme")
        assert ledger.count_today() == 1  # the failed reserve didn't insert a row


def test_caps_durable_across_processes(tmp_path):
    db = tmp_path / "caps.sqlite3"
    script = (
        "from job_apply_kit.caps import CapsConfig, CapsLedger\n"
        f"ledger = CapsLedger({str(db)!r}, config=CapsConfig(daily_cap=5, per_company_cap=5))\n"
        "ledger.reserve('Acme')\n"
        "ledger.close()\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = _SRC
    for _ in range(2):
        subprocess.run([sys.executable, "-c", script], check=True, env=env)

    config = CapsConfig(daily_cap=5, per_company_cap=5)
    with CapsLedger(db, config=config) as ledger:
        assert ledger.count_today() == 2
        assert ledger.count_company_7d("Acme") == 2


def test_daily_cap_day_boundary_bound_to_config_timezone_not_utc(tmp_path):
    # Q3 repro: the config says America/Chicago. Pick two timestamps that
    # fall on the SAME Chicago calendar day but straddle UTC midnight
    # (Chicago is UTC-6 in January, no DST to worry about) -- Chicago
    # Jan 1 17:00 and Chicago Jan 1 19:00 land on UTC Jan 1 23:00 and
    # UTC Jan 2 01:00 respectively. A ledger whose day boundary is bound
    # to UTC (instead of the config's tz) would wrongly see these as two
    # different days and let the second reserve through.
    db = tmp_path / "caps.sqlite3"
    config = CapsConfig(daily_cap=1, per_company_cap=5, tz="America/Chicago")
    first = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)
    second = datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc)
    with CapsLedger(db, config=config) as ledger:
        ledger.reserve("Acme", now=first)
        with pytest.raises(CapExceededError):
            ledger.reserve("OtherCo", now=second)


def test_reserve_rejects_naive_datetime(tmp_path):
    db = tmp_path / "caps.sqlite3"
    config = CapsConfig(daily_cap=5, per_company_cap=5)
    with CapsLedger(db, config=config) as ledger:
        with pytest.raises(ValueError):
            ledger.reserve("Acme", now=datetime(2026, 1, 1, 12, 0))  # no tzinfo


def test_stored_timestamps_are_utc_normalized(tmp_path):
    db = tmp_path / "caps.sqlite3"
    config = CapsConfig(daily_cap=5, per_company_cap=5)
    chicago_dt = datetime(2026, 1, 1, 1, 0, tzinfo=ZoneInfo("America/Chicago"))
    with CapsLedger(db, config=config) as ledger:
        ledger.reserve("Acme", now=chicago_dt)
        row = ledger._conn.execute("SELECT ts_utc FROM applications").fetchone()
        assert row[0] == chicago_dt.astimezone(timezone.utc).isoformat()


def test_daily_cap_using_local_chicago_timestamps_same_calendar_day(tmp_path):
    # repro: two same-Chicago-day timestamps expressed in Chicago's own
    # tz (not pre-converted to UTC by the caller). Before the ts_utc
    # normalization fix, storing raw (non-UTC) ISO offsets broke the
    # string range comparison used by count_today() and let the second
    # reserve slip through despite daily_cap=1.
    db = tmp_path / "caps.sqlite3"
    config = CapsConfig(daily_cap=1, per_company_cap=5, tz="America/Chicago")
    chicago = ZoneInfo("America/Chicago")
    first = datetime(2026, 1, 1, 1, 0, tzinfo=chicago)
    second = datetime(2026, 1, 1, 23, 0, tzinfo=chicago)
    with CapsLedger(db, config=config) as ledger:
        ledger.reserve("Acme", now=first)
        with pytest.raises(CapExceededError):
            ledger.reserve("OtherCo", now=second)
