from __future__ import annotations

import httpx
import pytest

from job_apply_kit.sources.lever import LeverError, fetch_jobs


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _patch(monkeypatch, status, payload=None):
    monkeypatch.setattr(
        httpx, "get", lambda url, params=None, timeout=None: _FakeResponse(status, payload)
    )


def test_fetch_jobs_parses_payload(monkeypatch):
    _patch(
        monkeypatch,
        200,
        [
            {
                "text": "Backend Engineer",
                "categories": {"location": "Remote"},
                "hostedUrl": "https://jobs.lever.co/example-co/1",
            },
            {"text": "no url, skipped"},
        ],
    )
    jobs = fetch_jobs("example-co")
    assert jobs == [
        {
            "title": "Backend Engineer",
            "location": "Remote",
            "url": "https://jobs.lever.co/example-co/1",
            "company": "example-co",
            "company_name": None,
            "description": "",
            "salary_amount": None,
            "salary_currency": "USD",
            "salary_period": "annual",
        }
    ]


def test_salary_range_passthrough_and_unknown_interval(monkeypatch):
    _patch(
        monkeypatch,
        200,
        [
            {
                "text": "a",
                "hostedUrl": "https://jobs.lever.co/x/1",
                "salaryRange": {
                    "min": 60,
                    "max": 80,
                    "currency": "eur",
                    "interval": "per-hour-wage",
                },
            },
            {
                "text": "b",
                "hostedUrl": "https://jobs.lever.co/x/2",
                "salaryRange": {"min": 5000, "currency": "USD", "interval": "one-time"},
            },
        ],
    )
    a, b = fetch_jobs("x")
    assert (a["salary_amount"], a["salary_currency"], a["salary_period"]) == (60, "EUR", "hourly")
    assert b["salary_amount"] is None


def test_404_raises(monkeypatch):
    _patch(monkeypatch, 404)
    with pytest.raises(LeverError, match="no Lever postings"):
        fetch_jobs("nonexistent")


def test_unexpected_shape_raises(monkeypatch):
    _patch(monkeypatch, 200, {"ok": False})
    with pytest.raises(LeverError, match="unexpected response shape"):
        fetch_jobs("x")
