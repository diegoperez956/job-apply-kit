#!/usr/bin/env python3
"""Scan for likely PII: email addresses, phone numbers, API-key-shaped
strings, and any terms listed in a user-supplied, gitignored terms file
(.pii_scan_terms.txt by default -- one term per line, e.g. your real
name, employer, or city; lines starting with # are comments).

Two modes:
  --staged (used by the pre-commit hook): scans exactly what's about to
    be committed -- the STAGED BLOB content (`git show :path`), not the
    working tree, so an edit made after `git add` can't slip past the
    scan. Covers added/copied/modified/renamed files
    (--diff-filter=ACMR). A staged binary file is REFUSED outright -- the
    commit fails with a clear reason -- unless its path is listed in
    .pii_scan_allow.txt (gitignored, one path per line). "Binary" is
    detected two ways, either is enough to refuse: (1) an extension on
    BINARY_REFUSE_SUFFIXES (resumes, screenshots, archives, office docs),
    or (2) a NUL byte anywhere in the first 8KB of the staged content --
    catches a binary file with an unlisted/renamed extension that would
    otherwise slip through untouched by the text scan below.
  no args: scans the whole git-tracked working tree instead (a broader,
    slower sanity check you can run any time; binary files -- by the same
    extension-or-content-sniff test -- are just skipped here since
    there's nothing to gate).

Exit code 0 = clean, 1 = findings printed as file:line: reason.

Wired as a pre-commit hook by scripts/install_hooks.sh; run with no args
to scan the whole tracked tree instead.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
API_KEY_RE = re.compile(
    r"\b("
    r"AKIA[0-9A-Z]{16}"  # AWS access key id
    r"|sk-[A-Za-z0-9]{20,}"  # OpenAI/Stripe/Anthropic-shaped secret key
    r"|gh[pousr]_[A-Za-z0-9]{20,}"  # GitHub tokens
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"  # Slack tokens
    r"|AIza[0-9A-Za-z_-]{35}"  # Google API key
    r")\b"
)

TERMS_FILE = Path(".pii_scan_terms.txt")
ALLOWLIST_FILE = Path(".pii_scan_allow.txt")

# Resumes, screenshots, archives, office docs -- refused outright when
# staged (see BINARY_REFUSE_SUFFIXES docstring above); this list is a
# floor, not the whole story -- _looks_binary() below catches anything
# with a NUL byte in it regardless of extension.
BINARY_REFUSE_SUFFIXES = {
    ".zip", ".gz", ".tar", ".7z",
    ".gif", ".bmp", ".webp", ".tiff",
    ".pdf", ".png", ".jpg", ".jpeg",
    ".docx", ".xlsx", ".pptx",
}  # fmt: skip

_NUL_SNIFF_BYTES = 8192


def _looks_binary(data: bytes) -> bool:
    """A NUL byte in the first 8KB is the standard cheap binary sniff
    (git and most `file`-style tools use the same heuristic) -- text
    files essentially never contain one."""
    return b"\x00" in data[:_NUL_SNIFF_BYTES]


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


def tracked_files() -> list[str]:
    return _git("ls-files")


def staged_files() -> list[str]:
    # --find-renames forces rename detection even if the caller's git
    # config disables it by default; ACMR keeps renamed files in scope.
    return _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "--find-renames")


def staged_blob_bytes(path: str) -> bytes | None:
    """The staged (about-to-be-committed) content of `path`, from the
    index -- not the working tree -- as raw bytes. Returns None if git
    can't produce it. Every path this is called with came straight from
    staged_files(), so a None here means the read itself failed (git
    error, race with the index, etc.), not that the path is legitimately
    unstaged -- scan_staged_file() below treats it as a scan failure,
    not a clean file, and fails the commit closed rather than silently
    skipping content it never actually looked at."""
    result = subprocess.run(["git", "show", f":{path}"], capture_output=True, check=False)
    if result.returncode != 0:
        return None
    return result.stdout


def staged_blob_text(path: str) -> str | None:
    """Text-decoded form of staged_blob_bytes(), for the text scanners."""
    data = staged_blob_bytes(path)
    return None if data is None else data.decode("utf-8", errors="ignore")


def _load_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def load_terms() -> list[str]:
    return _load_lines(TERMS_FILE)


def load_allowlist() -> set[str]:
    return set(_load_lines(ALLOWLIST_FILE))


def _scan_text(path: str, text: str, terms: list[str]) -> list[str]:
    findings = []
    for i, line in enumerate(text.splitlines(), start=1):
        if EMAIL_RE.search(line):
            findings.append(f"{path}:{i}: possible email address")
        if PHONE_RE.search(line):
            findings.append(f"{path}:{i}: possible phone number")
        if API_KEY_RE.search(line):
            findings.append(f"{path}:{i}: possible API key")
        for term in terms:
            if term.lower() in line.lower():
                findings.append(f"{path}:{i}: matches term from {TERMS_FILE.name}: {term!r}")
    return findings


def scan_file(path: Path, terms: list[str]) -> list[str]:
    """Whole-tree mode: read from the working tree, skip binaries (by
    extension, then by content) -- nothing to gate here, just avoid
    scanning garbage bytes as text."""
    if path.suffix.lower() in BINARY_REFUSE_SUFFIXES:
        return []
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if _looks_binary(data):
        return []
    return _scan_text(str(path), data.decode("utf-8", errors="ignore"), terms)


def scan_staged_file(path: str, terms: list[str], allowlist: set[str]) -> list[str]:
    """Staged mode: read the STAGED BLOB (git show :path), not the
    working tree. ANY staged binary content is refused outright --
    detected by a deny-listed extension OR a NUL byte in the first 8KB,
    either is enough -- unless the path is in the allowlist."""
    if path in allowlist:
        return []
    data = staged_blob_bytes(path)
    if data is None:
        # Fail closed: we couldn't read what's about to be committed, so
        # we can't vouch for it. A missing scan result must never look
        # like a clean one.
        return [f"{path}: could not read staged content — failing closed (refusing to scan blind)"]
    suffix = Path(path).suffix.lower()
    if suffix in BINARY_REFUSE_SUFFIXES or _looks_binary(data):
        return [
            f"{path}: binary artifact staged — resumes/screenshots/archives must not be committed"
        ]
    return _scan_text(path, data.decode("utf-8", errors="ignore"), terms)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    staged_only = "--staged" in argv
    terms = load_terms()

    all_findings: list[str] = []
    if staged_only:
        allowlist = load_allowlist()
        files = staged_files()
        for f in files:
            all_findings.extend(scan_staged_file(f, terms, allowlist))
    else:
        files = tracked_files()
        for f in files:
            p = Path(f)
            if not p.exists():
                continue
            all_findings.extend(scan_file(p, terms))

    if all_findings:
        print(f"pii_scan: {len(all_findings)} finding(s):")
        for line in all_findings:
            print(f"  {line}")
        return 1

    print(f"pii_scan: clean ({len(files)} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
