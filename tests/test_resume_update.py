from pathlib import Path

import pytest
import yaml

from job_apply_kit import cli
from job_apply_kit.integrations import IntegrationError
from job_apply_kit.resume_tailor import load_evidence


def prepare(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    Path("profile").mkdir()
    Path("profile/candidate_profile.yaml").write_text(
        yaml.safe_dump(profile.model_dump(mode="json"))
    )
    evidence = {
        "skills": {"value": ["SQL", "Python"], "state": "known"},
        "experience": [
            {
                "label": {"value": "Example role", "state": "known"},
                "bullets": {
                    "value": ["Maintained SQL reports", "Built Python tools"],
                    "state": "known",
                },
            },
            {
                "label": {"value": "Unverified role", "state": "requires_confirmation"},
                "bullets": {"value": ["Unverified claim"], "state": "requires_confirmation"},
            },
        ],
    }
    Path("profile/resume-draft.local.yaml").write_text(yaml.safe_dump(evidence))
    return evidence


def test_update_is_consumed_by_discovery_and_reorder_only_packets(tmp_path, monkeypatch, profile):
    expected = prepare(tmp_path, monkeypatch, profile)
    assert cli.main(["resume-update", "profile/resume-draft.local.yaml"]) == 0
    installed = load_evidence()
    assert installed.model_dump() == expected
    assert Path("profile/resume_evidence.yaml").stat().st_mode & 0o777 == 0o600
    assert cli.main(["discover", "--demo"]) == 0
    assert cli.main(["packet", "artifacts/ranked_jobs.jsonl"]) == 0
    packet = Path("artifacts/packet.md").read_text()
    assert "Built Python tools" in packet and "Maintained SQL reports" in packet
    assert "Unverified claim" not in packet
    # Updating preserves role/bullet membership and states; packets don't mutate source.
    assert load_evidence().model_dump() == expected
    expected["experience"][0]["bullets"]["value"].append("Reviewed new Python tests")
    Path("profile/resume-draft.local.yaml").write_text(yaml.safe_dump(expected))
    assert cli.main(["resume-update", "profile/resume-draft.local.yaml"]) == 0
    assert cli.main(["packet", "artifacts/ranked_jobs.jsonl"]) == 0
    assert "Reviewed new Python tests" in Path("artifacts/packet.md").read_text()


def test_check_does_not_write_or_promote_states(tmp_path, monkeypatch, profile, capsys):
    prepare(tmp_path, monkeypatch, profile)
    assert cli.main(["resume-update", "profile/resume-draft.local.yaml", "--check"]) == 0
    assert not Path("profile/resume_evidence.yaml").exists()
    assert "require confirmation" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["skills: [Python]", "[bad", "skills: {value: [], state: guessed}"])
def test_invalid_update_leaves_previous_evidence_intact(tmp_path, monkeypatch, profile, bad):
    prepare(tmp_path, monkeypatch, profile)
    assert cli.main(["resume-update", "profile/resume-draft.local.yaml"]) == 0
    old = Path("profile/resume_evidence.yaml").read_bytes()
    Path("profile/resume-draft.local.yaml").write_text(bad)
    assert cli.main(["resume-update", "profile/resume-draft.local.yaml"]) == 2
    assert Path("profile/resume_evidence.yaml").read_bytes() == old


def test_missing_source_and_invalid_profile_do_not_create_evidence(tmp_path, monkeypatch, profile):
    prepare(tmp_path, monkeypatch, profile)
    assert cli.main(["resume-update", "missing.yaml"]) == 2
    Path("profile/candidate_profile.yaml").write_text("[]")
    assert cli.main(["resume-update", "profile/resume-draft.local.yaml"]) == 2
    assert not Path("profile/resume_evidence.yaml").exists()


@pytest.mark.parametrize(
    "target", ["profile/resume_evidence.example.yaml", "profile/candidate_profile.yaml"]
)
def test_cannot_overwrite_public_example_or_candidate_profile(
    tmp_path, monkeypatch, profile, target
):
    prepare(tmp_path, monkeypatch, profile)
    before = Path("profile/candidate_profile.yaml").read_bytes()
    assert cli.main(["resume-update", "profile/resume-draft.local.yaml", "--evidence", target]) == 2
    assert Path("profile/candidate_profile.yaml").read_bytes() == before


def test_required_source_never_silently_returns_empty_evidence(tmp_path):
    path = tmp_path / "missing.yaml"
    assert load_evidence(path).experience == []  # Optional tailoring stays backward compatible.
    with pytest.raises(IntegrationError, match="must exist"):
        load_evidence(path, required=True)


def test_custom_evidence_path_and_in_place_update(tmp_path, monkeypatch, profile):
    expected = prepare(tmp_path, monkeypatch, profile)
    path = "profile/resume-draft.local.yaml"
    assert cli.main(["resume-update", path, "--evidence", path]) == 0
    assert load_evidence(Path(path)).model_dump() == expected
    assert cli.main(["discover", "--demo", "--evidence", path]) == 0
    assert cli.main(["packet", "artifacts/ranked_jobs.jsonl", "--evidence", path]) == 0
