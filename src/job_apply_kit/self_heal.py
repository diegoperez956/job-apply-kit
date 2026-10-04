"""Closed repair catalog: trim accidental board-slug whitespace, nothing else.

No generated patches, arbitrary commands, retries, source changes or safety edits.
All unknown failures remain reports for a human-maintained fix.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import tempfile
from pathlib import Path

import yaml

from .integrations import IntegrationError
from .run_log import RunLog, reference

BOARDS = Path("config/boards.yaml")
MAX_CHANGED_LINES = 60


def _proposal(text: str) -> tuple[str, list[tuple[str, str]]]:
    # Aliases/anchors could make a board edit also change an unrelated safety setting.
    if any(
        isinstance(t, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for t in yaml.scan(text)
    ):
        raise IntegrationError("report only: board YAML aliases/anchors need human review")
    expected = yaml.safe_load(text)
    root = yaml.compose(text)
    if not isinstance(root, yaml.MappingNode):
        raise IntegrationError("report only: boards must be a YAML mapping")
    edits = []
    targets = []
    for name, entries in root.value:
        key = {"greenhouse": "board_token", "lever": "slug", "ashby": "slug"}.get(name.value)
        if key is None:
            continue
        if not isinstance(entries, yaml.SequenceNode):
            raise IntegrationError("report only: board entries must be lists")
        for entry in entries.value:
            if not isinstance(entry, yaml.MappingNode):
                raise IntegrationError("report only: board entries must be mappings")
            for field, value in entry.value:
                if field.value != key:
                    continue
                if (
                    not isinstance(value, yaml.ScalarNode)
                    or value.tag != "tag:yaml.org,2002:str"
                    or value.style in {"|", ">"}
                ):
                    raise IntegrationError("report only: board slug must be text")
                trimmed = value.value.strip()
                if trimmed == value.value:
                    continue
                if not re.fullmatch(r"[A-Za-z0-9_-]+", trimmed):
                    raise IntegrationError("report only: uncertain board slug")
                edits.append((value.start_mark.index, value.end_mark.index, json.dumps(trimmed)))
                targets.append((name.value, value.value))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    for source, key in (("greenhouse", "board_token"), ("lever", "slug"), ("ashby", "slug")):
        for entry in expected.get(source, []) or []:
            if isinstance(entry.get(key), str):
                entry[key] = entry[key].strip()
    if yaml.safe_load(text) != expected:
        raise IntegrationError("report only: proposed repair changes more than board whitespace")
    return text, targets


def _replace(path: Path, content: bytes, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".self-heal-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _dry_run(text: str, targets: list[tuple[str, str]]) -> None:
    from .cli import SOURCES, _board_slugs, _require_mapping  # discover's own board loader

    boards = _require_mapping(yaml.safe_load(text), str(BOARDS))
    for source, slug in targets:
        loaded = _board_slugs(boards, source, SOURCES[source][0], BOARDS)
        if slug.strip() not in loaded or slug in loaded:
            raise IntegrationError("report only: repaired config does not load the trimmed board")


def heal(log: RunLog, *, apply: bool = False) -> int:
    report = log.report()
    print(json.dumps(report, indent=2))
    if not BOARDS.exists():
        print("Report only: no boards config; no repair available.")
        return 0
    if BOARDS.is_symlink() or BOARDS.parent.is_symlink():
        raise IntegrationError("report only: symlinked config is not repairable")
    original = BOARDS.read_bytes()
    repaired, targets = _proposal(original.decode())
    diff = list(difflib.unified_diff(original.decode().splitlines(), repaired.splitlines()))
    changed = sum(line.startswith(("+", "-")) for line in diff[2:])
    if not targets:
        print("Report only: no catalogued repair; review failures manually.")
        return 0
    if changed > MAX_CHANGED_LINES:
        raise IntegrationError("report only: repair exceeds 60 changed lines")
    # Only repair a config typo actually observed failing. Never infer a fix for
    # authentication, CAPTCHA, HTTP rate limits, malformed payloads or cap failures.
    failed = {
        (row["source"], row["target"])
        for row in report["failures"]
        if row["latest_outcome"] == "failure"
    }
    if any((source, reference(slug)) not in failed for source, slug in targets):
        print("Report only: whitespace found, but no matching observed board failure.")
        return 0
    _dry_run(repaired, targets)
    print(f"Catalogued repair: trim board whitespace ({changed} changed lines).")
    if not apply:
        print("Preview only; use self-heal --apply to repair.")
        return 0
    _replace(BOARDS, repaired.encode(), BOARDS.stat().st_mode & 0o777)
    log.record("self-heal", "success", code="board_whitespace_repaired")
    print("Repair applied; discovery loads the trimmed board(s). No safety settings changed.")
    return 0
