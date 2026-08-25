"""Candidate profile schema, loader, and validation.

The profile is the single source of truth every other module reads from.
Every fact is wrapped in a `Fact[T]` so the interview (and any code that
consumes the profile) can tell a confirmed answer from a guess:

- known:                 verified, safe to use anywhere (e.g. answering forms).
- preference:             a soft preference, safe to use for ranking/filtering
                          but should not be asserted as fact on a screener.
- requires_confirmation: the interview could not pin this down. Code that
                          answers application questions MUST treat this the
                          same as "unknown" (see answers.py) until a human
                          confirms it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Generic, Literal, TypeVar

import yaml
from pydantic import BaseModel, Field, ValidationError

FactState = Literal["known", "preference", "requires_confirmation"]

T = TypeVar("T")


class Fact(BaseModel, Generic[T]):
    value: T
    state: FactState = "requires_confirmation"


class ScreenerAnswer(BaseModel):
    question: str
    answer: str
    state: FactState = "requires_confirmation"


Period = Literal["annual", "monthly", "hourly"]


class CompFloor(BaseModel):
    """A comp floor is a bare number without currency/period is a trap --
    100000 means very different things as annual USD vs. hourly EUR."""

    amount: int
    currency: str = "USD"
    period: Period = "annual"


class Authorization(BaseModel):
    """Work authorization is per-country, not global: a candidate can be a
    citizen in one country and need sponsorship in another."""

    country: str
    status: str  # e.g. citizen, permanent_resident, visa_holder, needs_sponsorship
    sponsorship_required: bool


class SelfIdPrefs(BaseModel):
    """EEOC-style self-identification answers. Default is decline-to-answer;
    the interview never assumes a value here."""

    gender: Fact[str] = Field(default_factory=lambda: Fact(value="decline_to_answer"))
    race_ethnicity: Fact[str] = Field(default_factory=lambda: Fact(value="decline_to_answer"))
    veteran_status: Fact[str] = Field(default_factory=lambda: Fact(value="decline_to_answer"))
    disability_status: Fact[str] = Field(default_factory=lambda: Fact(value="decline_to_answer"))


class CandidateProfile(BaseModel):
    schema_version: int = 1

    target_roles: Fact[list[str]]
    seniority: Fact[str]

    # subset of {"remote", "hybrid", "onsite"} the candidate will accept
    location_mode: Fact[list[str]]
    # freeform region/city/state strings, e.g. "US-remote", "Austin, TX"
    geography: Fact[list[str]]
    # salary floor keyed by location mode
    comp_floor_by_mode: dict[str, Fact[CompFloor]] = Field(default_factory=dict)

    # per-country work authorization; see Authorization above
    authorizations: Fact[list[Authorization]]
    relocation: Fact[bool]
    relocation_notes: Fact[str | None] = Field(default_factory=lambda: Fact(value=None))

    start_date: Fact[str]
    non_compete: Fact[bool]
    non_compete_notes: Fact[str | None] = Field(default_factory=lambda: Fact(value=None))

    industries_to_avoid: Fact[list[str]] = Field(default_factory=lambda: Fact(value=[]))
    employer_blacklist: Fact[list[str]] = Field(default_factory=lambda: Fact(value=[]))
    dealbreakers: Fact[list[str]] = Field(default_factory=lambda: Fact(value=[]))

    self_id: SelfIdPrefs = Field(default_factory=SelfIdPrefs)
    links: Fact[dict[str, str]] = Field(default_factory=lambda: Fact(value={}))
    screener_answers: list[ScreenerAnswer] = Field(default_factory=list)


class ProfileError(ValueError):
    """Raised when a profile file is missing, malformed, or fails validation."""


def load_profile(path: str | Path) -> CandidateProfile:
    """Load and validate a candidate profile YAML file.

    Raises ProfileError with a human-readable message on any problem;
    never returns a partially-valid profile.
    """
    p = Path(path)
    if not p.exists():
        raise ProfileError(
            f"Profile not found at {p}. Run the /job-profile-interview skill "
            "(or copy profile/candidate_profile.example.yaml) to create one."
        )
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as e:
        raise ProfileError(f"{p} is not valid YAML: {e}") from e

    try:
        return CandidateProfile.model_validate(raw)
    except ValidationError as e:
        raise ProfileError(f"{p} failed schema validation:\n{e}") from e


def unconfirmed_facts(profile: CandidateProfile) -> list[str]:
    """Return dotted-path names of every fact still in requires_confirmation
    state, so callers can warn the user before relying on the profile."""
    unconfirmed: list[str] = []

    def walk(name: str, obj: object) -> None:
        if isinstance(obj, (Fact, ScreenerAnswer)):
            if obj.state == "requires_confirmation":
                unconfirmed.append(name)
            return
        if isinstance(obj, BaseModel):
            for field_name in type(obj).model_fields:
                walk(f"{name}.{field_name}" if name else field_name, getattr(obj, field_name))
        elif isinstance(obj, dict):
            for k, v in obj.items():
                walk(f"{name}.{k}", v)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(f"{name}[{i}]", v)

    walk("", profile)
    return unconfirmed
