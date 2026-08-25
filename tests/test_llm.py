from __future__ import annotations

import shutil

from job_apply_kit import llm


def test_is_available_false_when_not_on_path(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert llm.is_available() is False


def test_is_available_true_when_on_path(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/claude")
    assert llm.is_available() is True


def test_ask_returns_none_and_prints_notice_when_unavailable(monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    result = llm.ask("hello")
    assert result is None
    assert "claude` CLI not found" in capsys.readouterr().err


def test_ask_returns_stdout_on_success(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/claude")

    class _Result:
        returncode = 0
        stdout = "hi there\n"
        stderr = ""

    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: _Result())
    assert llm.ask("hello") == "hi there"


def test_ask_returns_none_on_nonzero_exit(monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/claude")

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: _Result())
    assert llm.ask("hello") is None
    assert "exited 1" in capsys.readouterr().err


def test_ask_returns_none_on_timeout(monkeypatch, capsys):
    import subprocess as _subprocess

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/claude")

    def _raise(*a, **k):
        raise _subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(llm.subprocess, "run", _raise)
    assert llm.ask("hello") is None
    assert "failed" in capsys.readouterr().err
