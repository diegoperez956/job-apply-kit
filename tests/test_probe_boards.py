from __future__ import annotations

import httpx

from job_apply_kit.sources.probe_boards import main, probe


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_probe_reports_not_found(monkeypatch, capsys):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(404)

    monkeypatch.setattr(httpx, "get", fake_get)
    code = probe(["nonexistent"], None)
    assert code == 1
    assert "NOT FOUND" in capsys.readouterr().out


def test_probe_reports_keyword_matches(monkeypatch, capsys):
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "Backend Engineer",
                "location": {"name": "Remote"},
                "absolute_url": "https://x/1",
            },
            {
                "id": 2,
                "title": "Sales Rep",
                "location": {"name": "Remote"},
                "absolute_url": "https://x/2",
            },
        ]
    }

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(200, payload)

    monkeypatch.setattr(httpx, "get", fake_get)
    code = probe(["acme"], "engineer")
    out = capsys.readouterr().out
    assert code == 0
    assert "2 open jobs, 1 match" in out
    assert "Backend Engineer" in out
    assert "Sales Rep" not in out


def test_probe_no_jobs_anywhere_is_exit_1(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(200, {"jobs": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    assert probe(["acme"], None) == 1


def test_main_parses_args_and_delegates(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(200, {"jobs": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    assert main(["acme", "--keyword", "engineer"]) == 1
