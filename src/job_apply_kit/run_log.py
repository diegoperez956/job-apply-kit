"""Private structured observations, not proof that an application was submitted."""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DEFAULT_RUN_LOG = Path("data/runs.sqlite3")


def reference(value: str) -> str:
    """Stable local correlation without persisting raw URLs, slugs or user content."""
    return hashlib.sha256(value.encode()).hexdigest()[:24] if value else "-"


class RunLog:
    def __init__(self, path: Path = DEFAULT_RUN_LOG):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, at TEXT NOT NULL, run TEXT NOT NULL,
            command TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL,
            outcome TEXT NOT NULL, code TEXT NOT NULL)""")
        self.db.commit()
        self.run = uuid4().hex

    def close(self) -> None:
        self.db.close()

    def record(
        self,
        command: str,
        outcome: str,
        *,
        source: str = "kit",
        target: str = "",
        code: str = "",
    ) -> None:
        # Callers supply fixed codes/exception class names, NEVER exception messages,
        # job text, profile values, environment variables or HTTP response bodies.
        with self.db:
            self.db.execute(
                "INSERT INTO events(at,run,command,source,target,outcome,code) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    self.run,
                    command,
                    source,
                    reference(target),
                    outcome,
                    code,
                ),
            )

    def report(self, limit: int = 20, target: str | None = None) -> dict:
        if not 1 <= limit <= 200:
            raise ValueError("status limit must be between 1 and 200")
        self.db.row_factory = sqlite3.Row
        where, params = ("WHERE target = ?", [reference(target)]) if target else ("", [])
        rows = self.db.execute(
            f"SELECT * FROM events {where} ORDER BY id DESC LIMIT ?", [*params, limit]
        ).fetchall()
        failures = self.db.execute(
            f"""SELECT source,target,command,count(*) AS failures,max(at) AS last_failure,
            (SELECT outcome FROM events AS latest
             WHERE latest.source = events.source AND latest.target = events.target
               AND latest.command = events.command AND latest.outcome != 'started'
             ORDER BY latest.id DESC LIMIT 1) AS latest_outcome
            FROM events {where + " AND" if where else "WHERE"} outcome = 'failure'
            GROUP BY source,target,command ORDER BY last_failure DESC LIMIT ?""",
            [*params, limit],
        ).fetchall()
        return {
            "recent": [dict(row) for row in rows],
            "failures": [dict(row) for row in failures],
            "note": "Local preparation observations only; never submission confirmation.",
        }


class BestEffortLog:
    """Observation for ordinary commands: an unavailable log warns once, never blocks work."""

    def __init__(self, path: Path = DEFAULT_RUN_LOG):
        self.log: RunLog | None = None
        try:
            self.log = RunLog(path)
        except (sqlite3.Error, OSError) as e:
            self._disable(e)

    def _disable(self, error: Exception) -> None:
        print(f"run observation unavailable: {type(error).__name__}", file=sys.stderr)
        log, self.log = self.log, None
        if log is not None:
            log.close()

    def record(self, *args, **kwargs) -> None:
        if self.log is None:
            return
        try:
            self.log.record(*args, **kwargs)
        except (sqlite3.Error, OSError) as e:
            self._disable(e)

    def close(self) -> None:
        if self.log is not None:
            self.log.close()
