from __future__ import annotations

import pytest

from job_apply_kit.tier import TierConfigError, detect_tier, load_tier_overrides


def test_greenhouse_boards_is_tier_1():
    assert detect_tier("https://boards.greenhouse.io/example-co/jobs/12345") == 1
    assert detect_tier("boards.greenhouse.io") == 1


def test_workday_is_tier_2():
    assert detect_tier("https://acme.myworkdayjobs.com/careers/job/123") == 2


def test_unknown_host_is_tier_3():
    assert detect_tier("https://careers.some-random-startup.example/apply") == 3


def test_overrides_win_over_defaults():
    overrides = {"boards.greenhouse.io": 3}
    assert detect_tier("https://boards.greenhouse.io/x", overrides=overrides) == 3


def test_overrides_add_new_hosts():
    overrides = {"jobs.example-ats.com": 2}
    assert detect_tier("https://jobs.example-ats.com/apply/1", overrides=overrides) == 2


def test_blank_input_is_tier_3():
    assert detect_tier("") == 3


def test_lever_and_ashby_default_to_tier_2_no_implemented_source():
    # jobs.lever.co / jobs.ashbyhq.com have public job-board APIs but no
    # fetch client in sources/ yet -- see Q4/tier.py.
    assert detect_tier("https://jobs.lever.co/acme/xyz") == 2
    assert detect_tier("https://jobs.ashbyhq.com/acme") == 2


def test_load_tier_overrides_rejects_invalid_tier_value(tmp_path):
    p = tmp_path / "overrides.yaml"
    p.write_text("some.ats.example.com: 4\n")
    with pytest.raises(TierConfigError):
        load_tier_overrides(p)


def test_load_tier_overrides_rejects_non_integer_tier(tmp_path):
    p = tmp_path / "overrides.yaml"
    p.write_text("some.ats.example.com: not-a-number\n")
    with pytest.raises(TierConfigError):
        load_tier_overrides(p)


def test_load_tier_overrides_clamps_tier1_to_tier2_for_unimplemented_source(tmp_path, capsys):
    p = tmp_path / "overrides.yaml"
    p.write_text("myworkdayjobs.com: 1\n")
    overrides = load_tier_overrides(p)
    assert overrides["myworkdayjobs.com"] == 2
    assert "clamping to tier 2" in capsys.readouterr().err


def test_load_tier_overrides_allows_tier1_for_greenhouse_boards(tmp_path):
    p = tmp_path / "overrides.yaml"
    p.write_text("job-boards.greenhouse.io: 1\n")
    overrides = load_tier_overrides(p)
    assert overrides["job-boards.greenhouse.io"] == 1


def test_load_tier_overrides_missing_file_is_empty(tmp_path):
    assert load_tier_overrides(tmp_path / "nope.yaml") == {}


# Q4 repro: detect_tier() must validate a directly-passed overrides dict
# the same way it validates a loaded file -- a dict handed straight in
# is not a trusted shortcut around the tier-1-capability check.


def test_detect_tier_clamps_direct_dict_override_for_unimplemented_host(capsys):
    result = detect_tier("https://evil.example/apply", {"evil.example": 1})
    assert result == 2
    assert "clamping to tier 2" in capsys.readouterr().err


def test_detect_tier_rejects_invalid_tier_value_in_direct_dict():
    with pytest.raises(TierConfigError):
        detect_tier("https://example.com/apply", {"example.com": 9})


# Q3 repro: only an exact int 1|2|3 is a valid tier value -- bool, float,
# and numeral strings must all be rejected, not silently coerced.


def test_validate_overrides_rejects_bool_tier(tmp_path):
    p = tmp_path / "overrides.yaml"
    p.write_text("some.ats.example.com: true\n")
    with pytest.raises(TierConfigError):
        load_tier_overrides(p)


def test_validate_overrides_rejects_float_tier(tmp_path):
    p = tmp_path / "overrides.yaml"
    p.write_text("some.ats.example.com: 2.9\n")
    with pytest.raises(TierConfigError):
        load_tier_overrides(p)


def test_validate_overrides_rejects_string_tier(tmp_path):
    p = tmp_path / "overrides.yaml"
    p.write_text('some.ats.example.com: "2"\n')
    with pytest.raises(TierConfigError):
        load_tier_overrides(p)


def test_detect_tier_rejects_bool_tier_in_direct_dict():
    with pytest.raises(TierConfigError):
        detect_tier("https://example.com/apply", {"example.com": True})
