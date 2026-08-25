from __future__ import annotations

import subprocess

import pii_scan


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _fake_email(local: str, domain: str) -> str:
    # Built at runtime rather than written as a literal "x@y.z" so this
    # test file itself doesn't trip pii_scan's own email regex when it's
    # committed -- the scanner works on source text, and can't tell a
    # test fixture from a real address.
    return f"{local}@{domain}"


def _init_repo(path):
    _git("init", "-q", cwd=path)
    _git("config", "user.email", _fake_email("test", "example.com"), cwd=path)
    _git("config", "user.name", "Test", cwd=path)


def test_scan_staged_blob_ignores_working_tree_edits_after_add(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    f = tmp_path / "notes.txt"
    f.write_text("clean line\n")
    _git("add", "notes.txt", cwd=tmp_path)
    # dirty the working tree after staging -- staged scan must ignore this.
    f.write_text(_fake_email("real.email", "example.com") + "\n")
    monkeypatch.chdir(tmp_path)
    assert pii_scan.scan_staged_file("notes.txt", [], set()) == []


def test_scan_staged_blob_flags_staged_content(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    f = tmp_path / "notes.txt"
    f.write_text(_fake_email("real.email", "example.com") + "\n")
    _git("add", "notes.txt", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    findings = pii_scan.scan_staged_file("notes.txt", [], set())
    assert any("possible email" in x for x in findings)


def test_binary_refused_in_staged_mode(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    f = tmp_path / "resume.pdf"
    f.write_bytes(b"%PDF-1.4 fake binary content")
    _git("add", "resume.pdf", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    findings = pii_scan.scan_staged_file("resume.pdf", [], set())
    assert len(findings) == 1
    assert "binary artifact staged" in findings[0]


def test_binary_allowlisted_is_skipped_not_scanned(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    f = tmp_path / "resume.pdf"
    f.write_bytes(b"%PDF-1.4 fake binary content")
    _git("add", "resume.pdf", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    findings = pii_scan.scan_staged_file("resume.pdf", [], {"resume.pdf"})
    assert findings == []


def test_zip_archive_refused_in_staged_mode(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    f = tmp_path / "resume.zip"
    f.write_bytes(b"PK\x03\x04fake zip content")
    _git("add", "resume.zip", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    findings = pii_scan.scan_staged_file("resume.zip", [], set())
    assert len(findings) == 1
    assert "binary artifact staged" in findings[0]


def test_gif_screenshot_refused_in_staged_mode(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    f = tmp_path / "screenshot.gif"
    f.write_bytes(b"GIF89a\x00\x00fake gif content")
    _git("add", "screenshot.gif", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    findings = pii_scan.scan_staged_file("screenshot.gif", [], set())
    assert len(findings) == 1
    assert "binary artifact staged" in findings[0]


def test_binary_content_refused_even_with_unlisted_extension(tmp_path, monkeypatch):
    # No extension on the deny-list, but a NUL byte in the content is
    # enough on its own to refuse it -- content sniff, not just suffix.
    _init_repo(tmp_path)
    f = tmp_path / "notes.txt"
    f.write_bytes(b"looks like text\x00but has a NUL byte")
    _git("add", "notes.txt", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    findings = pii_scan.scan_staged_file("notes.txt", [], set())
    assert len(findings) == 1
    assert "binary artifact staged" in findings[0]


def test_staged_files_includes_renames(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    f = tmp_path / "old.txt"
    f.write_text("hello world, this file has enough content to be detected as a rename\n")
    _git("add", "old.txt", cwd=tmp_path)
    _git("commit", "-m", "init", "-q", cwd=tmp_path)
    (tmp_path / "old.txt").rename(tmp_path / "new.txt")
    _git("add", "-A", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    files = pii_scan.staged_files()
    assert "new.txt" in files


def test_main_staged_mode_fails_commit_on_finding(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    f = tmp_path / "notes.txt"
    f.write_text(_fake_email("real.email", "example.com") + "\n")
    _git("add", "notes.txt", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    assert pii_scan.main(["--staged"]) == 1


def test_main_staged_mode_clean_is_zero(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    f = tmp_path / "notes.txt"
    f.write_text("nothing interesting here\n")
    _git("add", "notes.txt", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    assert pii_scan.main(["--staged"]) == 0


# Q5 repro: a staged blob the scanner can't read must fail closed, never
# be silently treated as clean.


def test_scan_staged_blob_read_failure_fails_closed(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    findings = pii_scan.scan_staged_file("does-not-exist.txt", [], set())
    assert len(findings) == 1
    assert "could not read staged content" in findings[0]


def test_main_staged_mode_fails_closed_on_blob_read_failure(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    f = tmp_path / "notes.txt"
    f.write_text("nothing interesting here\n")
    _git("add", "notes.txt", cwd=tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pii_scan, "staged_blob_bytes", lambda path: None)
    assert pii_scan.main(["--staged"]) == 1
