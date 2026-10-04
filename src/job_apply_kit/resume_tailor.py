"""Portable, reorder-only resume evidence. No text generation or PDF template."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .integrations import IntegrationError
from .jd_requirements import clean_description
from .profile import Fact

DEFAULT_EVIDENCE = Path("profile/resume_evidence.yaml")


class ResumeBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Fact[str]
    bullets: Fact[list[str]]


class ResumeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skills: Fact[list[str]] = Field(default_factory=lambda: Fact(value=[]))
    experience: list[ResumeBlock] = Field(default_factory=list)


def load_evidence(path: Path = DEFAULT_EVIDENCE) -> ResumeEvidence:
    if not path.exists():
        return ResumeEvidence()
    try:
        return ResumeEvidence.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise IntegrationError("invalid resume evidence; check its Fact values/states") from exc


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def reorder_evidence(evidence: ResumeEvidence, job: dict) -> ResumeEvidence:
    tokens = _tokens(
        str(job.get("title") or "") + " " + clean_description(job.get("description") or "")
    )
    requirements = job.get("requirements") or {}
    for skill in requirements.get("required_skills", []) + requirements.get("preferred_skills", []):
        tokens |= _tokens(skill)

    def order(items: list[str]) -> list[str]:
        # Python's stable sort keeps equal-scoring items in their original order.
        return sorted(items, key=lambda text: -len(_tokens(text) & tokens))

    result = evidence.model_copy(deep=True)
    if result.skills.state == "known":
        result.skills.value = order(result.skills.value)
    for block in result.experience:
        if block.bullets.state == "known":
            block.bullets.value = order(block.bullets.value)
    return result
