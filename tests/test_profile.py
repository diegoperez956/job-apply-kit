from __future__ import annotations

from pathlib import Path

import pytest

from job_apply_kit.profile import ProfileError, load_profile, unconfirmed_facts

EXAMPLE = Path(__file__).parent.parent / "profile" / "candidate_profile.example.yaml"


def test_loads_example_profile():
    p = load_profile(EXAMPLE)
    assert p.schema_version == 1
    assert p.target_roles.value


def test_missing_file_raises():
    with pytest.raises(ProfileError, match="not found"):
        load_profile("/nonexistent/path/candidate_profile.yaml")


def test_invalid_yaml_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("target_roles: [unterminated")
    with pytest.raises(ProfileError, match="not valid YAML"):
        load_profile(bad)


def test_schema_violation_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: 1\n")  # missing required fields
    with pytest.raises(ProfileError, match="schema validation"):
        load_profile(bad)


def test_unconfirmed_facts_reports_requires_confirmation(profile):
    assert unconfirmed_facts(profile) == []

    p = load_profile(EXAMPLE)
    unconfirmed = unconfirmed_facts(p)
    assert "authorizations" in unconfirmed
