from __future__ import annotations

import pytest

from job_apply_kit.caps import (
    CapConfigError,
    CapsConfig,
    load_caps_from_env,
)


def test_zero_daily_cap_is_config_error():
    with pytest.raises(CapConfigError):
        CapsConfig(daily_cap=0, per_company_cap=1)


def test_zero_per_company_cap_is_config_error():
    with pytest.raises(CapConfigError):
        CapsConfig(daily_cap=5, per_company_cap=0)


def test_negative_cap_is_config_error():
    with pytest.raises(CapConfigError):
        CapsConfig(daily_cap=-1, per_company_cap=1)


def test_load_caps_from_env_missing_raises():
    with pytest.raises(CapConfigError):
        load_caps_from_env({})


def test_load_caps_from_env_non_integer_raises():
    with pytest.raises(CapConfigError):
        load_caps_from_env({"JOB_APPLY_DAILY_CAP": "abc", "JOB_APPLY_PER_COMPANY_CAP": "1"})


def test_load_caps_from_env_ok():
    cfg = load_caps_from_env({"JOB_APPLY_DAILY_CAP": "10", "JOB_APPLY_PER_COMPANY_CAP": "2"})
    assert cfg.daily_cap == 10
    assert cfg.per_company_cap == 2
