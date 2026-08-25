from __future__ import annotations

import httpx
import pytest

from job_apply_kit.sources.greenhouse import GreenhouseError, fetch_jobs


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_jobs_parses_payload(monkeypatch):
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "Software Engineer",
                "location": {"name": "Remote"},
                "absolute_url": "https://example.com/1",
            },
            {
                "id": 2,
                "title": "Backend Engineer",
                "location": {"name": "Austin, TX"},
                "absolute_url": "https://example.com/2",
            },
        ]
    }

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(200, payload)

    monkeypatch.setattr(httpx, "get", fake_get)

    jobs = fetch_jobs("example-co")
    assert len(jobs) == 2
    assert jobs[0].title == "Software Engineer"
    assert jobs[0].location == "Remote"
    assert jobs[0].board_token == "example-co"


def test_fetch_jobs_404_raises(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(GreenhouseError, match="no Greenhouse board"):
        fetch_jobs("nonexistent")


def test_fetch_jobs_unexpected_shape_raises(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(200, {"unexpected": "shape"})

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(GreenhouseError, match="unexpected response shape"):
        fetch_jobs("example-co")


# Q6 repro: company display name and pay_input_ranges passthrough.


def test_fetch_jobs_passes_through_company_name_and_pay_range(monkeypatch):
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "Software Engineer",
                "location": {"name": "Remote"},
                "absolute_url": "https://example.com/1",
                "company_name": "Acme Inc",
                "pay_input_ranges": [
                    {"min_cents": 12000000, "max_cents": 15000000, "currency_type": "USD"}
                ],
            }
        ]
    }

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(200, payload)

    monkeypatch.setattr(httpx, "get", fake_get)

    jobs = fetch_jobs("acme")
    assert jobs[0].company_name == "Acme Inc"
    assert jobs[0].salary_amount == 120000
    assert jobs[0].salary_currency == "USD"
    assert jobs[0].salary_period == "annual"


def test_fetch_jobs_no_pay_range_leaves_salary_none(monkeypatch):
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "Software Engineer",
                "location": {"name": "Remote"},
                "absolute_url": "https://example.com/1",
            }
        ]
    }

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(200, payload)

    monkeypatch.setattr(httpx, "get", fake_get)

    jobs = fetch_jobs("acme")
    assert jobs[0].company_name is None
    assert jobs[0].salary_amount is None
