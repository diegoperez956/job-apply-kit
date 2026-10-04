from __future__ import annotations

import json
from pathlib import Path

import httpx
import yaml

from job_apply_kit import cli


def _profile(tmp_path, profile):
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile/candidate_profile.yaml").write_text(
        yaml.safe_dump(profile.model_dump(mode="json"))
    )


def test_no_key_cli_flow_discover_rank_packet_is_offline(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    _profile(tmp_path, profile)
    assert cli.main(["setup", "--jev", "no", "--simplify", "no"]) == 0
    assert cli.main(["discover", "--demo"]) == 0
    assert cli.main(["rank", "artifacts/ranked_jobs.jsonl"]) == 0
    assert cli.main(["packet", "artifacts/ranked_jobs.jsonl"]) == 0
    rows = [
        json.loads(line)
        for line in (tmp_path / "artifacts/ranked_jobs.jsonl").read_text().splitlines()
    ]
    assert rows[0]["requirements"] is None
    assert rows[0]["requirements_source"] == "keyword"
    packet = (tmp_path / "artifacts/packet.md").read_text()
    assert "No confirmed work bullets" in packet
    assert "submit by hand" in packet
    assert not (tmp_path / "data/jev.sqlite3").exists()


def test_fake_key_flow_uses_one_mocked_jev_request_and_packet_reuses_snapshot(
    tmp_path, monkeypatch, profile
):
    monkeypatch.chdir(tmp_path)
    _profile(tmp_path, profile)
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-" + "workflow-key")
    calls = []

    def server(request):
        calls.append(request)
        body = json.loads(request.content)
        answers = {}
        for name, question in body["questions"].items():
            choice = "required" if name.startswith("skill::") else "unspecified"
            answers[name] = {
                "choice": choice,
                "confidence": 1,
                "probabilities": {key: int(key == choice) for key in question["criteria"]},
            }
        return httpx.Response(200, json={"answers": answers})

    transport = httpx.MockTransport(server)
    assert (
        cli.main(
            [
                "setup",
                "--jev",
                "yes",
                "--simplify",
                "no",
                "--daily-budget",
                "1",
                "--monthly-budget",
                "2",
            ]
        )
        == 0
    )
    assert cli.main(["discover", "--demo"], jev_transport=transport) == 0
    assert cli.main(["rank", "artifacts/ranked_jobs.jsonl", "--demo"], jev_transport=transport) == 0
    assert cli.main(["packet", "artifacts/ranked_jobs.jsonl"]) == 0
    assert len(calls) == 1
    row = json.loads((tmp_path / "artifacts/ranked_jobs.jsonl").read_text())
    assert row["requirements"]["min_years"] == 2
    assert row["requirements"]["required_skills"] == ["Python", "SQL"]
    assert row["requirements_source"] == "jev"
    # Accidentally dropping demo mode cannot bill the real endpoint for fake jobs.
    assert cli.main(["rank", "artifacts/ranked_jobs.jsonl"]) == 2


def test_simplify_handoff_requires_optin_risk_and_caps(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    _profile(tmp_path, profile)
    job = {
        "title": "Example Engineer",
        "company": "Example Co",
        "url": "https://jobs.lever.co/example-co/1",
        "location": "Remote",
    }
    Path("jobs.jsonl").write_text(json.dumps(job) + "\n")
    command = ["packet", "jobs.jsonl", "--simplify"]
    assert cli.main(command) == 2
    assert cli.main(["setup", "--jev", "no", "--simplify", "yes"]) == 0
    assert cli.main(command) == 2  # Opt-in without explicit risk acceptance is insufficient.
    assert cli.main(["setup", "--jev", "no", "--simplify", "yes", "--accept-simplify-risk"]) == 0
    monkeypatch.delenv("JOB_APPLY_DAILY_CAP", raising=False)
    monkeypatch.delenv("JOB_APPLY_PER_COMPANY_CAP", raising=False)
    assert cli.main(command) == 2
    assert not Path("artifacts/packet.md").exists()
    monkeypatch.setenv("JOB_APPLY_DAILY_CAP", "2")
    monkeypatch.setenv("JOB_APPLY_PER_COMPANY_CAP", "1")
    assert cli.main(command) == 0
    packet = Path("artifacts/packet.md").read_text()
    assert "Simplify Copilot" in packet
    assert "EVERY field" in packet and "Only a human clicks submit" in packet
    assert cli.main(command + ["--out", "artifacts/second.md"]) == 2
    assert not Path("artifacts/second.md").exists()


def test_current_blacklist_blocks_packet_even_for_an_old_ranked_job(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _profile(tmp_path, profile)
    Path("config").mkdir()
    Path("config/blacklist.yaml").write_text("companies: [Example Co]\n")
    Path("jobs.jsonl").write_text(
        json.dumps(
            {
                "title": "Example Engineer",
                "company": "Example Co",
                "url": "https://jobs.lever.co/example-co/1",
            }
        )
        + "\n"
    )
    assert cli.main(["packet", "jobs.jsonl"]) == 2
    assert not Path("artifacts/packet.md").exists()


def test_mocked_public_sources_forward_jds_to_optional_jev(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _profile(tmp_path, profile)
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-" + "key")
    Path("config").mkdir()
    Path("config/boards.yaml").write_text(
        "greenhouse: [{board_token: example-green}]\n"
        "lever: [{slug: example-lever}]\nashby: [{slug: example-ashby}]\n"
    )

    def source(url, **kwargs):
        if "greenhouse" in url:
            payload = {
                "jobs": [
                    {
                        "id": 1,
                        "title": "Example Role",
                        "absolute_url": "https://boards.greenhouse.io/example-green/jobs/1",
                        "content": "<p>Greenhouse fixture requirements</p>",
                    }
                ]
            }
        elif "lever" in url:
            payload = [
                {
                    "text": "Example Role",
                    "hostedUrl": "https://jobs.lever.co/example-lever/1",
                    "descriptionPlain": "Lever fixture requirements",
                }
            ]
        else:
            payload = {
                "jobs": [
                    {
                        "title": "Example Role",
                        "jobUrl": "https://jobs.ashbyhq.com/example-ashby/1",
                        "descriptionHtml": "<p>Ashby fixture requirements</p>",
                    }
                ]
            }
        return httpx.Response(200, json=payload)

    descriptions = []

    def jev(request):
        descriptions.append(json.loads(request.content)["state"]["description"])
        return httpx.Response(200, json={"answers": {}})

    monkeypatch.setattr(httpx, "get", source)
    assert (
        cli.main(
            [
                "setup",
                "--jev",
                "yes",
                "--simplify",
                "no",
                "--daily-budget",
                "1",
                "--monthly-budget",
                "2",
            ]
        )
        == 0
    )
    assert cli.main(["discover"], jev_transport=httpx.MockTransport(jev)) == 0
    assert set(descriptions) == {
        "Greenhouse fixture requirements",
        "Lever fixture requirements",
        "Ashby fixture requirements",
    }
    rows = [
        json.loads(line) for line in Path("artifacts/ranked_jobs.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 3 and all(row["requirements_source"] == "jev" for row in rows)


def test_demo_cannot_authorize_simplify_and_invalid_jsonl_is_controlled(
    tmp_path, monkeypatch, profile
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    _profile(tmp_path, profile)
    assert cli.main(["discover", "--demo"]) == 0
    assert cli.main(["packet", "artifacts/ranked_jobs.jsonl", "--simplify"]) == 2
    Path("bad.jsonl").write_text(json.dumps({"url": "https://example.invalid/", "title": {}}))
    assert cli.main(["rank", "bad.jsonl"]) == 2
