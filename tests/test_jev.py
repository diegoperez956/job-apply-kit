from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

import httpx
import pytest

from job_apply_kit.integrations import Integrations
from job_apply_kit.jd_requirements import JevClient

POSTING = {
    "url": "https://jobs.lever.co/example-co/1",
    "title": "Example Engineer",
    "company": "example-co",
    "description": "<p>Requirements: 5+ years of experience. Python required.</p>",
}


def test_jev_is_off_by_default_and_missing_key_never_calls(tmp_path, monkeypatch):
    def forbidden(request):
        raise AssertionError("unexpected billable request")

    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-" + "test-key")
    client = JevClient(
        Integrations(), db=tmp_path / "cache.db", transport=httpx.MockTransport(forbidden)
    )
    assert client.get(POSTING, ["Python"]) is None
    monkeypatch.delenv("TYPESAFE_API_KEY")
    client = JevClient(
        Integrations(jev_enabled=True),
        db=tmp_path / "cache.db",
        transport=httpx.MockTransport(forbidden),
    )
    assert client.get(POSTING, ["Python"]) is None
    assert not (tmp_path / "cache.db").exists()


def _response(request, choices=None):
    body = json.loads(request.content)
    choices = choices or {"min_years": "2", "skill::Python": "required"}
    answers = {}
    for name, question in body["questions"].items():
        choice = choices.get(name, "unspecified")
        if choice not in question["criteria"]:
            choice = next(iter(question["criteria"]))
        answers[name] = {
            "choice": choice,
            "confidence": 1.0,
            "probabilities": {key: int(key == choice) for key in question["criteria"]},
        }
    return httpx.Response(200, json={"answers": answers, "usage": {"input_tokens": 100}})


def test_one_direct_api_call_per_job_persists_across_process_clients(tmp_path, monkeypatch):
    key = "fake-" + "test-credential"
    monkeypatch.setenv("TYPESAFE_API_KEY", key)
    calls = []

    def server(request):
        calls.append(request)
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["Authorization"] == f"Bearer {key}"
        payload = json.loads(request.content)
        assert payload["model"] == "jev-1.13.0"
        assert "<p>" not in payload["state"]["description"]
        assert len(payload["questions"]) <= 32
        assert all(q["type"] == "choice" for q in payload["questions"].values())
        return _response(request)

    settings = Integrations(jev_enabled=True, jev_daily_usd="0.1", jev_monthly_usd="1")
    db = tmp_path / "cache.db"
    client = JevClient(settings, db=db, transport=httpx.MockTransport(server))
    result = client.get(POSTING, ["Python"])
    assert result["min_years"] == 5  # Full JD regex wins over the differing model choice.
    assert result["required_skills"] == ["Python"]
    restart = JevClient(settings, db=db, transport=httpx.MockTransport(server))
    assert restart.get(POSTING, ["Python"]) == result
    assert len(calls) == 1
    assert key.encode() not in db.read_bytes()


@pytest.mark.parametrize("daily,monthly", [("0", "1"), ("1", "0"), ("0.000001", "1")])
def test_local_budget_gate_prevents_call(tmp_path, monkeypatch, daily, monthly):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-" + "key")
    transport = httpx.MockTransport(lambda _: pytest.fail("budget did not block call"))
    client = JevClient(
        Integrations(
            jev_enabled=True,
            jev_daily_usd=daily,
            jev_monthly_usd=monthly,
        ),
        db=tmp_path / "cache.db",
        transport=transport,
    )
    assert client.get(POSTING, []) is None
    assert "budget" in client.last_status


@pytest.mark.parametrize("failure", ["http", "timeout", "json", "redirect"])
def test_failed_or_uncertain_request_is_not_retried_and_errors_are_sanitized(
    tmp_path, monkeypatch, failure
):
    key = "fake-" + "private-key"
    monkeypatch.setenv("TYPESAFE_API_KEY", key)
    calls = []

    def server(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout(key, request=request)
        if failure == "json":
            return httpx.Response(200, text=key)
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.invalid/"})
        return httpx.Response(403, text=key)

    settings = Integrations(jev_enabled=True, jev_daily_usd="1", jev_monthly_usd="2")
    client = JevClient(settings, db=tmp_path / "cache.db", transport=httpx.MockTransport(server))
    assert client.get(POSTING, []) is None
    assert key not in client.last_status
    restart = JevClient(settings, db=tmp_path / "cache.db", transport=httpx.MockTransport(server))
    assert restart.get(POSTING, []) is None
    assert len(calls) == 1


def test_partial_invalid_answers_do_not_poison_other_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-" + "key")

    def server(request):
        response = _response(request, {"skill::Python": "preferred", "degree_required": "bachelor"})
        body = response.json()
        body["answers"]["clearance_required"]["confidence"] = True
        body["answers"]["work_mode"]["probabilities"] = {"remote": 1}
        body["answers"]["sponsorship_offered"]["choice"] = "invented"
        return httpx.Response(200, json=body)

    client = JevClient(
        Integrations(jev_enabled=True, jev_daily_usd="1", jev_monthly_usd="2"),
        db=tmp_path / "cache.db",
        transport=httpx.MockTransport(server),
    )
    result = client.get({**POSTING, "description": "Python preferred."}, ["Python"])
    assert result["clearance_required"] is None
    assert result["work_mode"] is None
    assert result["sponsorship_offered"] is None
    assert result["degree_required"] == "bachelor"
    assert result["preferred_skills"] == ["Python"]


def test_skill_questions_and_jd_are_bounded_and_requirements_prioritized(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-" + "key")

    def server(request):
        body = json.loads(request.content)
        assert len(body["questions"]) == 31
        assert len(body["state"]["description"]) <= 4000
        assert body["state"]["description"].startswith("Requirements")
        assert len(request.content) <= 32768
        return _response(request)

    client = JevClient(
        Integrations(jev_enabled=True, jev_daily_usd="1", jev_monthly_usd="2"),
        db=tmp_path / "cache.db",
        transport=httpx.MockTransport(server),
    )
    assert (
        client.get(
            {
                **POSTING,
                "description": "About us. " * 1000
                + "&lt;p&gt;Requirements: Python &amp;amp; SQL.&lt;/p&gt;",
            },
            [f"Skill{i}" for i in range(50)],
        )
        is not None
    )


def test_concurrent_clients_claim_job_before_transport(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-" + "key")
    calls = []
    lock = Lock()

    def server(request):
        with lock:
            calls.append(request)
        sleep(0.02)
        return _response(request)

    settings = Integrations(jev_enabled=True, jev_daily_usd="1", jev_monthly_usd="2")
    db = tmp_path / "cache.db"

    def run(_):
        return JevClient(settings, db=db, transport=httpx.MockTransport(server)).get(POSTING, [])

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert len(calls) == 1
    assert any(result is not None for result in results)
    assert run(None)["min_years"] == 5
    assert len(calls) == 1


def test_actual_usage_blocks_next_job_and_corrupt_cache_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-" + "key")
    calls = []

    def server(request):
        calls.append(request)
        body = _response(request).json()
        body["usage"] = {"input_tokens": 1000000}
        return httpx.Response(200, json=body)

    db = tmp_path / "cache.db"
    client = JevClient(
        Integrations(
            jev_enabled=True,
            jev_daily_usd="0.01",
            jev_monthly_usd="0.1",
        ),
        db=db,
        transport=httpx.MockTransport(server),
    )
    assert client.get(POSTING, []) is not None
    assert client.get({**POSTING, "url": POSTING["url"] + "-new"}, []) is None
    assert len(calls) == 1
    broken = tmp_path / "broken.db"
    broken.write_text("not a database")
    assert (
        JevClient(client.settings, db=broken, transport=httpx.MockTransport(server)).get(
            POSTING, []
        )
        is None
    )
    assert len(calls) == 1
