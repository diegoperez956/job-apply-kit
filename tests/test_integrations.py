from __future__ import annotations

import pytest
import yaml

from job_apply_kit import cli
from job_apply_kit.integrations import IntegrationError, load_integrations


def test_post_interview_setup_declines_both_integrations(tmp_path, monkeypatch, profile, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile/candidate_profile.yaml").write_text(
        yaml.safe_dump(profile.model_dump(mode="json"))
    )
    assert cli.main(["setup", "--jev", "no", "--simplify", "no"]) == 0
    config = yaml.safe_load((tmp_path / "config/integrations.local.yaml").read_text())
    assert config["jev_enabled"] is False
    assert config["simplify_enabled"] is False
    assert "absent" in capsys.readouterr().out


def test_setup_asks_one_optin_at_a_time_and_never_saves_key(tmp_path, monkeypatch, profile, capsys):
    monkeypatch.chdir(tmp_path)
    key = "fake-" + "credential-for-test"
    monkeypatch.setenv("TYPESAFE_API_KEY", key)
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile/candidate_profile.yaml").write_text(
        yaml.safe_dump(profile.model_dump(mode="json"))
    )
    replies = iter(["yes", "0.02", "0.50", "yes", "yes"])
    prompts = []

    def respond(prompt):
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr("builtins.input", respond)
    assert cli.main(["setup"]) == 0
    settings = load_integrations()
    assert settings.jev_enabled and settings.simplify_enabled
    assert settings.simplify_risk_accepted
    assert str(settings.jev_daily_usd) == "0.02"
    assert prompts[0].startswith("Wire in Jev?")
    assert prompts[3].startswith("Use Simplify")
    assert key not in capsys.readouterr().out
    path = tmp_path / "config/integrations.local.yaml"
    assert key not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600


def test_setup_requires_profile_before_asking(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("asked before interview"))
    assert cli.main(["setup"]) == 2
    assert not (tmp_path / "config/integrations.local.yaml").exists()


@pytest.mark.parametrize("value", ["-1", "nan", "Infinity", "oops"])
def test_setup_invalid_budget_does_not_enable_jev(tmp_path, monkeypatch, profile, value):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile.model_dump(mode="json")))
    assert (
        cli.main(
            [
                "setup",
                "--profile",
                str(path),
                "--jev",
                "yes",
                "--simplify",
                "no",
                "--daily-budget",
                value,
            ]
        )
        == 2
    )
    assert not load_integrations().jev_enabled


def test_unrecognized_local_config_is_rejected_without_echoing_content(tmp_path):
    path = tmp_path / "local.yaml"
    value = "fake-" + "pasted-key"
    path.write_text(f"credential: {value}\n")
    with pytest.raises(IntegrationError) as exc:
        load_integrations(path)
    assert value not in str(exc.value)
