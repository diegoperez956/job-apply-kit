from pathlib import Path

import pytest
import yaml

from job_apply_kit import cli, self_heal
from job_apply_kit.cli import ConfigStructureError
from job_apply_kit.integrations import IntegrationError
from job_apply_kit.run_log import RunLog


@pytest.fixture
def repair_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("config").mkdir()
    text = '# keep comment\ngreenhouse: [{board_token: " example-co "}]\n'
    text += "unrelated_safety_setting: false\n"
    self_heal.BOARDS.write_text(text)
    log = RunLog()
    log.record(
        "discover", "failure", source="greenhouse", target=" example-co ", code="GreenhouseError"
    )
    yield log, text
    log.close()


def test_preview_never_writes(repair_case):
    log, original = repair_case
    assert self_heal.heal(log) == 0
    assert self_heal.BOARDS.read_text() == original


def test_known_repair_preserves_all_other_fields(repair_case):
    log, original = repair_case
    assert self_heal.heal(log, apply=True) == 0
    repaired = self_heal.BOARDS.read_text()
    assert repaired == original.replace('" example-co "', '"example-co"')
    assert yaml.safe_load(repaired)["unrelated_safety_setting"] is False
    assert log.report()["recent"][0]["code"] == "board_whitespace_repaired"


def test_repair_that_discovery_cannot_load_is_not_applied(repair_case):
    log, _ = repair_case
    text = 'greenhouse: [{board_token: " example-co "}, {name: missing-token}]\n'
    self_heal.BOARDS.write_text(text)
    with pytest.raises(ConfigStructureError):
        self_heal.heal(log, apply=True)
    assert self_heal.BOARDS.read_text() == text


def test_line_budget_is_enforced(repair_case):
    log, _ = repair_case
    text = "greenhouse:\n" + ('  - board_token: " example-co "\n' * 31)
    self_heal.BOARDS.write_text(text)
    with pytest.raises(IntegrationError, match="60 changed lines"):
        self_heal.heal(log, apply=True)
    assert self_heal.BOARDS.read_text() == text


def test_unobserved_and_unknown_failures_report_only(repair_case):
    log, _ = repair_case
    text = 'lever: [{slug: " unknown-board "}]\n'
    self_heal.BOARDS.write_text(text)
    log.record("packet", "failure", code="CapExceededError")
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
def test_uncertain_config_is_not_modified(repair_case, text):
    log, _ = repair_case
    self_heal.BOARDS.write_text(text)
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


def test_cli_exposes_report_and_apply_flow(repair_case):
    _, original = repair_case
    assert cli.main(["self-heal"]) == 0
    assert self_heal.BOARDS.read_text() == original
    assert cli.main(["self-heal", "--apply"]) == 0
    assert self_heal.BOARDS.read_text() == original.replace('" example-co "', '"example-co"')


def test_repair_never_touches_protections_or_other_files(repair_case):
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
    assert self_heal.heal(log, apply=True) == 0
    assert {filename: Path(filename).read_text() for filename in protected} == protected


def test_later_success_closes_observed_failure(repair_case):
    log, original = repair_case
    log.record("discover", "success", source="greenhouse", target=" example-co ")
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
