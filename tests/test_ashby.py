from __future__ import annotations

import httpx
import pytest

from job_apply_kit.sources.ashby import AshbyError, fetch_jobs


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


def test_fetch_jobs_parses_payload_and_skips_unlisted(monkeypatch):
    _patch(
        monkeypatch,
        200,
        {
            "jobs": [
                {
                    "title": "Data Engineer",
                    "location": "New York",
                    "jobUrl": "https://jobs.ashbyhq.com/example-co/1",
                    "compensation": {
                        "summaryComponents": [
                            {"compensationType": "EquityPercentage", "minValue": 0.1},
                            {
                                "compensationType": "Salary",
                                "interval": "1 YEAR",
                                "currencyCode": "USD",
                                "minValue": 150000,
                                "maxValue": 190000,
                            },
                        ]
                    },
                },
                {
                    "title": "hidden",
                    "jobUrl": "https://jobs.ashbyhq.com/example-co/2",
                    "isListed": False,
                },
            ]
        },
    )
    jobs = fetch_jobs("example-co")
    assert len(jobs) == 1
    job = jobs[0]
    assert (job["title"], job["location"], job["company"]) == (
        "Data Engineer",
        "New York",
        "example-co",
    )
    assert (job["salary_amount"], job["salary_currency"], job["salary_period"]) == (
        150000,
        "USD",
        "annual",
    )


def test_unknown_interval_is_unknown_salary(monkeypatch):
    _patch(
        monkeypatch,
        200,
        {
            "jobs": [
                {
                    "title": "a",
                    "jobUrl": "https://jobs.ashbyhq.com/x/1",
                    "compensation": {
                        "summaryComponents": [
                            {"compensationType": "Salary", "interval": "1 WEEK", "minValue": 2000}
                        ]
                    },
                }
            ]
        },
    )
    assert fetch_jobs("x")[0]["salary_amount"] is None


def test_404_raises(monkeypatch):
    _patch(monkeypatch, 404)
    with pytest.raises(AshbyError, match="no Ashby job board"):
        fetch_jobs("nonexistent")


def test_unexpected_shape_raises(monkeypatch):
    _patch(monkeypatch, 200, {"unexpected": "shape"})
    with pytest.raises(AshbyError, match="unexpected response shape"):
        fetch_jobs("x")
