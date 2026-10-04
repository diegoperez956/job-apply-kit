import subprocess
from pathlib import Path

import pytest
import yaml

from job_apply_kit import cli, self_heal
from job_apply_kit.integrations import IntegrationError
from job_apply_kit.run_log import RunLog


@pytest.fixture
def repair_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("config").mkdir()
    Path("tests").mkdir()
    Path("pyproject.toml").write_text("# fictional test checkout\n")
    text = '# keep comment\ngreenhouse: [{board_token: " example-co "}]\n'
    text += "unrelated_safety_setting: false\n"
    self_heal.BOARDS.write_text(text)
    log = RunLog()
    log.record(
        "discover", "failure", source="greenhouse", target=" example-co ", code="GreenhouseError"
    )
    yield log, text
    log.close()


def test_preview_never_runs_tests_or_writes(repair_case, monkeypatch):
    log, original = repair_case
    monkeypatch.setattr(self_heal, "_tests", lambda: pytest.fail("preview ran tests"))
    assert self_heal.heal(log) == 0
    assert self_heal.BOARDS.read_text() == original


def test_known_repair_preserves_all_other_fields_and_tests_before_after(repair_case, monkeypatch):
    log, original = repair_case
    snapshots = []

    def tests():
        snapshots.append(self_heal.BOARDS.read_text())
        return True

    monkeypatch.setattr(self_heal, "_tests", tests)
    assert self_heal.heal(log, apply=True) == 0
    assert snapshots == [original, original.replace('" example-co "', '"example-co"')]
    assert yaml.safe_load(snapshots[1])["unrelated_safety_setting"] is False
    assert log.report()["recent"][0]["code"] == "board_whitespace_repaired"


@pytest.mark.parametrize("results,expected_calls", [([False], 1), ([True, False], 2)])
def test_failing_tests_prevent_or_rollback_repair(
    repair_case, monkeypatch, results, expected_calls
):
    log, original = repair_case
    calls = []

    def tests():
        calls.append(True)
        return results[len(calls) - 1]

    monkeypatch.setattr(self_heal, "_tests", tests)
    with pytest.raises(IntegrationError):
        self_heal.heal(log, apply=True)
    assert self_heal.BOARDS.read_text() == original
    assert len(calls) == expected_calls


def test_interrupted_post_tests_roll_back(repair_case, monkeypatch):
    log, original = repair_case
    calls = []

    def tests():
        calls.append(True)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return True

    monkeypatch.setattr(self_heal, "_tests", tests)
    with pytest.raises(KeyboardInterrupt):
        self_heal.heal(log, apply=True)
    assert self_heal.BOARDS.read_text() == original


def test_line_budget_is_enforced(repair_case, monkeypatch):
    log, _ = repair_case
    text = "greenhouse:\n" + ('  - board_token: " example-co "\n' * 31)
    self_heal.BOARDS.write_text(text)
    monkeypatch.setattr(self_heal, "_tests", lambda: pytest.fail("oversized repair ran tests"))
    with pytest.raises(IntegrationError, match="60 changed lines"):
        self_heal.heal(log, apply=True)
    assert self_heal.BOARDS.read_text() == text


def test_unobserved_and_unknown_failures_report_only(repair_case, monkeypatch):
    log, _ = repair_case
    text = 'lever: [{slug: " unknown-board "}]\n'
    self_heal.BOARDS.write_text(text)
    log.record("packet", "failure", code="CapExceededError")
    monkeypatch.setattr(self_heal, "_tests", lambda: pytest.fail("unknown repair ran tests"))
    assert self_heal.heal(log, apply=True) == 0
    assert self_heal.BOARDS.read_text() == text


@pytest.mark.parametrize(
    "text",
    [
        'greenhouse: [{board_token: &slug " example-co "}]\nsafety: *slug\n',
        'greenhouse: [{board_token: " ../example-co "}]\n',
        'greenhouse: [{board_token: "   "}]\n',
        "greenhouse: [{board_token: [bad]}]\n",
        "greenhouse: [bad]\n",
        "greenhouse: {bad: value}\n",
        "[bad]\n",
    ],
)
def test_uncertain_config_is_not_modified(repair_case, monkeypatch, text):
    log, _ = repair_case
    self_heal.BOARDS.write_text(text)
    monkeypatch.setattr(self_heal, "_tests", lambda: pytest.fail("unsafe repair ran tests"))
    with pytest.raises(IntegrationError):
        self_heal.heal(log, apply=True)
    assert self_heal.BOARDS.read_text() == text


def test_cannot_repair_symlinked_config(repair_case):
    log, original = repair_case
    self_heal.BOARDS.rename("config/original.yaml")
    self_heal.BOARDS.symlink_to("original.yaml")
    with pytest.raises(IntegrationError, match="symlinked"):
        self_heal.heal(log, apply=True)
    assert Path("config/original.yaml").read_text() == original


def test_config_changed_during_tests_is_not_overwritten(repair_case, monkeypatch):
    log, _ = repair_case

    def tests():
        self_heal.BOARDS.write_text("# concurrent user edit\n")
        return True

    monkeypatch.setattr(self_heal, "_tests", tests)
    with pytest.raises(IntegrationError, match="changed during"):
        self_heal.heal(log, apply=True)
    assert self_heal.BOARDS.read_text() == "# concurrent user edit\n"


def test_repair_without_checkout_tests_is_report_only(repair_case, monkeypatch):
    log, original = repair_case
    Path("pyproject.toml").unlink()
    monkeypatch.setattr(self_heal, "_tests", lambda: pytest.fail("missing checkout ran tests"))
    with pytest.raises(IntegrationError, match="checkout"):
        self_heal.heal(log, apply=True)
    assert self_heal.BOARDS.read_text() == original


def test_cli_exposes_report_and_apply_flow(repair_case, monkeypatch):
    _, original = repair_case
    monkeypatch.setattr(self_heal, "_tests", lambda: True)
    assert cli.main(["self-heal"]) == 0
    assert self_heal.BOARDS.read_text() == original
    assert cli.main(["self-heal", "--apply"]) == 0
    assert self_heal.BOARDS.read_text() == original.replace('" example-co "', '"example-co"')


def test_subprocess_gate_is_fixed_and_offline(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    assert self_heal._tests()
    assert calls[0][0][1:] == ["-m", "pytest", "-q"]
    assert calls[0][1]["timeout"] == 120


def test_subprocess_timeout_is_not_green(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("pytest", 120)

    monkeypatch.setattr(subprocess, "run", run)
    assert not self_heal._tests()


def test_repair_never_touches_protections_or_other_files(repair_case, monkeypatch):
    log, _ = repair_case
    protected = {
        "config/blacklist.yaml": "companies: [Example Co]\n",
        "config/integrations.local.yaml": "jev_enabled: false\nsimplify_enabled: false\n",
        "config/tier_overrides.yaml": "example.invalid: 3\n",
        "sources/adapter.py": "# stop on challenges; human submits\n",
        "tests/test_guard.py": "# caps and fact checks remain intact\n",
    }
    for filename, text in protected.items():
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    monkeypatch.setattr(self_heal, "_tests", lambda: True)
    assert self_heal.heal(log, apply=True) == 0
    assert {filename: Path(filename).read_text() for filename in protected} == protected


def test_later_success_closes_observed_failure(repair_case, monkeypatch):
    log, original = repair_case
    log.record("discover", "success", source="greenhouse", target=" example-co ")
    monkeypatch.setattr(self_heal, "_tests", lambda: pytest.fail("resolved failure ran tests"))
    assert self_heal.heal(log, apply=True) == 0
    assert self_heal.BOARDS.read_text() == original
    assert log.report()["failures"][0]["latest_outcome"] == "success"


def test_block_scalar_requires_human_review(repair_case):
    log, _ = repair_case
    text = "greenhouse:\n  - board_token: >\n      example-co\nother: false\n"
    self_heal.BOARDS.write_text(text)
    with pytest.raises(IntegrationError):
        self_heal.heal(log, apply=True)
    assert self_heal.BOARDS.read_text() == text


def test_post_test_concurrent_change_is_not_claimed_as_repaired(repair_case, monkeypatch):
    log, _ = repair_case
    calls = []

    def tests():
        calls.append(True)
        if len(calls) == 2:
            self_heal.BOARDS.write_text("# concurrent user change\n")
        return True

    monkeypatch.setattr(self_heal, "_tests", tests)
    with pytest.raises(IntegrationError, match="changed during post"):
        self_heal.heal(log, apply=True)
    assert self_heal.BOARDS.read_text() == "# concurrent user change\n"
