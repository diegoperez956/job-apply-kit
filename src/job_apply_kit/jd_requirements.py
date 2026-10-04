"""Optional TypeSafe System One extraction. No key or opt-in: keyword-only."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field, StrictBool, StrictInt

from .integrations import Integrations, typesafe_key

JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-1.13.0"
INPUT_TOKEN_RATE = Decimal("0.000000042")  # USD/input token; verify current provider pricing.
MAX_BODY_BYTES = 32768

_CHOICES = {
    "min_years": {
        **{str(n): f"minimum {n} years" for n in range(10)},
        "10_or_more": "at least 10 years",
        "unspecified": "no minimum stated",
    },
    "clearance_required": {
        "required": "clearance required",
        "not_required": "no clearance",
        "unspecified": "not stated",
    },
    "degree_required": {
        "none": "no degree required",
        "associate": "associate degree",
        "bachelor": "bachelor degree",
        "master": "master degree",
        "phd": "doctoral degree",
        "unspecified": "not stated",
    },
    "work_mode": {
        "remote": "fully remote",
        "hybrid": "some office days",
        "onsite": "in office",
        "unspecified": "not stated",
    },
    "sponsorship_offered": {
        "yes": "explicitly offered",
        "no": "explicitly unavailable",
        "unspecified": "not stated",
    },
    "seniority": {
        "intern": "internship",
        "entry": "entry level",
        "mid": "mid level",
        "senior": "senior level",
        "staff": "staff level",
        "principal": "principal",
        "unspecified": "not stated",
    },
}
_SKILL_CHOICES = {
    "required": "explicitly required",
    "preferred": "nice to have",
    "not_mentioned": "not mentioned",
}
_HEADINGS = (
    "qualifications",
    "requirements",
    "what you'll need",
    "what you bring",
    "what we're looking for",
    "about you",
    "minimum",
    "preferred",
)


class Requirements(BaseModel):
    min_years: StrictInt | None = Field(default=None, ge=0)
    clearance_required: StrictBool | None = None
    degree_required: Literal["none", "associate", "bachelor", "master", "phd"] | None = None
    work_mode: Literal["remote", "hybrid", "onsite"] | None = None
    sponsorship_offered: Literal["yes", "no"] | None = None
    seniority: Literal["intern", "entry", "mid", "senior", "staff", "principal"] | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)


def clean_description(raw: str) -> str:
    if not isinstance(raw, str):
        return ""
    text = re.sub(r"<[^>]+>", " ", html.unescape(raw))
    return " ".join(html.unescape(text).replace("’", "'").split())


def _description_window(text: str) -> str:
    if len(text) <= 4000:
        return text
    starts = [text.lower().index(h) for h in _HEADINGS if h in text.lower()]
    start = min(starts) if starts else 0
    priority = text[start : start + 4000]
    remaining = 4000 - len(priority)
    return (priority + " " + text[: max(0, remaining - 1)]).strip()[:4000]


def _questions(skills: list[str]) -> dict:
    questions = {
        name: {
            "type": "choice",
            "instructions": f"Extract {name} from the job description; "
            "choose unspecified when it is not explicitly stated.",
            "criteria": criteria,
        }
        for name, criteria in _CHOICES.items()
    }
    for skill in skills:
        questions[f"skill::{skill}"] = {
            "type": "choice",
            "instructions": f"Is the skill {skill!r} required or preferred?",
            "criteria": _SKILL_CHOICES,
        }
    return questions


def _choice(answer: object, criteria: dict) -> str | None:
    if not isinstance(answer, dict):
        return None
    choice, confidence, probabilities = (
        answer.get("choice"),
        answer.get("confidence"),
        answer.get("probabilities"),
    )
    if not isinstance(choice, str) or choice not in criteria:
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    if not 0 <= confidence <= 1:
        return None
    if not isinstance(probabilities, dict) or set(probabilities) != set(criteria):
        return None
    values = list(probabilities.values())
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1 for v in values
    ):
        return None
    if abs(sum(values) - 1) > len(values) * 0.005 + 1e-9:
        return None
    return choice


def _parse(document: dict, questions: dict, description: str, skills: list[str]) -> dict:
    answers = document.get("answers")
    answers = answers if isinstance(answers, dict) else {}
    labels = {name: _choice(answers.get(name), q["criteria"]) for name, q in questions.items()}
    years = labels.get("min_years")
    result = {
        name: (None if labels[name] in {None, "unspecified"} else labels[name]) for name in _CHOICES
    }
    result["min_years"] = (
        10
        if years == "10_or_more"
        else int(years)
        if years is not None and years.isdigit()
        else None
    )
    # The first plain numeric years requirement uses the FULL cleaned JD, not its window.
    match = re.search(r"(\d+)\+?\s*(?:or\s+more\s+)?years", description, re.I)
    if match and len(match.group(1)) <= 3:
        result["min_years"] = int(match.group(1))
    result["clearance_required"] = {"required": True, "not_required": False}.get(
        labels.get("clearance_required")
    )
    result["required_skills"] = [s for s in skills if labels.get(f"skill::{s}") == "required"]
    result["preferred_skills"] = [s for s in skills if labels.get(f"skill::{s}") == "preferred"]
    return result


class JevClient:
    def __init__(
        self,
        settings: Integrations,
        *,
        db: Path = Path("data/jev.sqlite3"),
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.db = db
        self.transport = transport
        self.last_status = "keyword-only"

    def get(self, posting: dict, skills: list[str]) -> dict | None:
        key = typesafe_key()
        self.last_status = "keyword-only: disabled or missing key"
        if not self.settings.jev_enabled or not key or not posting.get("url"):
            return None
        skills = list(
            dict.fromkeys(
                s.strip() for s in skills if isinstance(s, str) and s.strip() and len(s) <= 80
            )
        )[:25]
        description = clean_description(posting.get("description") or "")
        questions = _questions(skills)
        body = json.dumps(
            {
                "model": JEV_MODEL,
                "state": {
                    "title": str(posting.get("title") or "")[:300],
                    "company": str(posting.get("company") or "")[:300],
                    "description": _description_window(description),
                },
                "questions": questions,
            }
        ).encode()
        if len(body) > MAX_BODY_BYTES or not description:
            self.last_status = "keyword-only: missing JD or oversized request"
            return None
        job_key = hashlib.sha256(posting["url"].split("#")[0].encode()).hexdigest()
        # Reserve conservatively before calling; failed/uncertain attempts stay charged.
        # Local estimate is not a guarantee about provider-wide billing or price changes.
        reserve = Decimal(len(body) + 4096) * INPUT_TOKEN_RATE
        try:
            cached, claimed = self._claim(job_key, reserve)
            if not claimed:
                return cached
            return self._extract(job_key, body, key, questions, description, skills, reserve)
        except (sqlite3.Error, OSError, ValueError, InvalidOperation):
            self.last_status = "keyword-only: local cache unavailable"
            return None

    def _connect(self):
        self.db.parent.mkdir(parents=True, exist_ok=True)
        if self.db.is_symlink():
            raise OSError("symlinked cache refused")
        if not self.db.exists():
            fd = os.open(self.db, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        conn = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS attempts (job_key TEXT PRIMARY KEY, "
            "created_at TEXT NOT NULL, cost_usd TEXT NOT NULL, result TEXT)"
        )
        return conn

    def _claim(self, job_key: str, reserve: Decimal) -> tuple[dict | None, bool]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cached = conn.execute(
                "SELECT result FROM attempts WHERE job_key=?", (job_key,)
            ).fetchone()
            if cached is not None:
                self.last_status = "cached Jev" if cached[0] else "keyword-only: previous attempt"
                return (
                    Requirements.model_validate_json(cached[0]).model_dump() if cached[0] else None
                ), False
            now = datetime.now(timezone.utc).isoformat()
            rows = conn.execute("SELECT created_at, cost_usd FROM attempts").fetchall()
            daily = sum((Decimal(cost) for date, cost in rows if date[:10] == now[:10]), Decimal(0))
            monthly = sum((Decimal(cost) for date, cost in rows if date[:7] == now[:7]), Decimal(0))
            if (
                daily + reserve > self.settings.jev_daily_usd
                or monthly + reserve > self.settings.jev_monthly_usd
            ):
                self.last_status = "keyword-only: local budget exhausted"
                return None, False
            conn.execute(
                "INSERT INTO attempts VALUES (?, ?, ?, NULL)", (job_key, now, str(reserve))
            )
            self.last_status = "Jev"
            return None, True
        finally:
            if conn.in_transaction:
                conn.commit()
            conn.close()

    def _extract(self, job_key, body, key, questions, description, skills, reserve):
        try:
            with httpx.Client(
                timeout=10, follow_redirects=False, transport=self.transport
            ) as client:
                response = client.post(
                    JEV_ENDPOINT,
                    content=body,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                if len(response.content) > 131072:
                    self.last_status = "keyword-only: oversized Jev response"
                    return None
                document = response.json()
            if not isinstance(document, dict):
                self.last_status = "keyword-only: invalid Jev response"
                return None
        except (httpx.HTTPError, ValueError):
            # No raw request/response/error bodies or credentials in diagnostics.
            self.last_status = "keyword-only: Jev request failed"
            return None
        requirements = _parse(document, questions, description, skills)
        usage = document.get("usage")
        tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
        actual = (
            Decimal(tokens) * INPUT_TOKEN_RATE
            if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0
            else reserve
        )
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE attempts SET result=?, cost_usd=? WHERE job_key=?",
                (json.dumps(requirements), str(max(reserve, actual)), job_key),
            )
        finally:
            conn.close()
        return requirements
