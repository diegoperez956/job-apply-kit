import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from job_apply_kit import cli
from job_apply_kit.run_log import RunLog, reference
from job_apply_kit.sources.greenhouse import GreenhouseError


def read_log():
    log = RunLog()
    try:
        return log.report(200)
    finally:
        log.close()


def prepare(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    Path("profile").mkdir()
    Path("profile/candidate_profile.yaml").write_text(
        yaml.safe_dump(profile.model_dump(mode="json"))
    )


def test_source_failures_are_observed_even_if_discover_returns_success(
    tmp_path, monkeypatch, profile, capsys
):
    prepare(tmp_path, monkeypatch, profile)
    Path("config").mkdir()
    Path("config/boards.yaml").write_text(
        "greenhouse: [{board_token: example-failing}, {board_token: example-ok}]\n"
    )

    def fetch(slug):
        if slug == "example-failing":
            raise GreenhouseError("private-response-sentinel")
        return []

    monkeypatch.setattr(cli, "fetch_jobs", fetch)
    assert cli.main(["discover"]) == 0
    report = read_log()
    failure = report["failures"][0]
    assert failure["source"] == "greenhouse"
    assert failure["target"] == reference("example-failing")
    assert failure["failures"] == 1
    assert any(
        row["source"] == "greenhouse" and row["outcome"] == "success" for row in report["recent"]
    )
    capsys.readouterr()
    assert cli.main(["run-status", "--target", "example-failing"]) == 0
    filtered = json.loads(capsys.readouterr().out)
    assert len(filtered["recent"]) == 1
    assert "private-response-sentinel" not in Path("data/runs.sqlite3").read_bytes().decode(
        errors="ignore"
    )
    assert "example-failing" not in json.dumps(report)


def test_application_failure_and_success_correlate_without_storing_raw_url(
    tmp_path, monkeypatch, profile
):
    prepare(tmp_path, monkeypatch, profile)
    url = "https://jobs.lever.co/example-role/1?secret=private-url-sentinel"
    Path("jobs.jsonl").write_text(json.dumps({"url": url, "title": "Example role"}))
    assert cli.main(["packet", "jobs.jsonl", "--simplify"]) == 2
    assert cli.main(["packet", "jobs.jsonl"]) == 0
    report = read_log()
    assert report["failures"][0]["target"] == reference(url)
    assert report["failures"][0]["command"] == "packet"
    events = [row for row in report["recent"] if row["target"] == reference(url)]
    assert {row["outcome"] for row in events} == {"success", "failure"}
    assert "private-url-sentinel" not in json.dumps(report)
    assert "private-url-sentinel" not in Path("data/runs.sqlite3").read_bytes().decode(
        errors="ignore"
    )


def test_unexpected_source_breakage_is_logged_and_not_silently_skipped(
    tmp_path, monkeypatch, profile
):
    prepare(tmp_path, monkeypatch, profile)
    Path("config").mkdir()
    Path("config/boards.yaml").write_text("greenhouse: [{board_token: example-co}]\n")

    def broken(slug):
        raise KeyError("private-payload-sentinel")

    monkeypatch.setattr(cli, "fetch_jobs", broken)
    with pytest.raises(KeyError):
        cli.main(["discover"])
    report = read_log()
    assert {row["source"] for row in report["failures"]} == {"kit", "greenhouse"}
    assert "private-payload-sentinel" not in json.dumps(report)
    assert {row["code"] for row in report["recent"] if row["outcome"] == "failure"} == {"KeyError"}


def test_run_status_is_read_only_and_validates_limit(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["run-status"]) == 0
    assert json.loads(capsys.readouterr().out)["recent"] == []
    assert cli.main(["run-status", "--limit", "0"]) == 2
    assert read_log()["recent"] == []


def test_invalid_config_records_failure_without_raw_content(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("bad.yaml").write_text("private-profile-sentinel")
    assert cli.main(["interview-check", "--profile", "bad.yaml"]) == 1
    report = read_log()
    assert report["recent"][0]["outcome"] == "failure"
    assert report["recent"][0]["code"] == "exit_1"
    assert "private-profile-sentinel" not in json.dumps(report)


@pytest.mark.parametrize("command", ["run-status", "self-heal"])
def test_unreadable_log_blocks_only_log_commands(tmp_path, monkeypatch, profile, capsys, command):
    prepare(tmp_path, monkeypatch, profile)
    Path("data").mkdir()
    Path("data/runs.sqlite3").write_text("not a database")
    assert cli.main(["interview-check"]) == 0
    assert "run observation unavailable: DatabaseError" in capsys.readouterr().err
    assert cli.main([command]) == 2


def test_log_outage_mid_discovery_does_not_abort_or_mask_board_errors(
    tmp_path, monkeypatch, profile, capsys
):
    prepare(tmp_path, monkeypatch, profile)
    Path("config").mkdir()
    Path("config/boards.yaml").write_text(
        "greenhouse: [{board_token: example-failing}, {board_token: example-ok}]\n"
    )
    real_record = RunLog.record

    def record(self, command, outcome, **kwargs):
        if outcome != "started":
            raise sqlite3.OperationalError("database is locked")
        real_record(self, command, outcome, **kwargs)

    def fetch(slug):
        if slug == "example-failing":
            raise GreenhouseError("board gone")
        return []

    monkeypatch.setattr(RunLog, "record", record)
    monkeypatch.setattr(cli, "fetch_jobs", fetch)
    assert cli.main(["discover"]) == 0
    err = capsys.readouterr().err
    assert "skipping greenhouse board 'example-failing'" in err
    assert err.count("run observation unavailable") == 1
