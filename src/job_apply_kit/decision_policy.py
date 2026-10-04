"""Requirements assist human review; they never answer screening questions."""

from __future__ import annotations

from .profile import CandidateProfile


def requirement_mismatches(requirements: dict | None, profile: CandidateProfile) -> list[str]:
    if not requirements:
        return []
    reasons = []
    years = profile.experience_years
    minimum = requirements.get("min_years")
    if (
        years.state == "known"
        and years.value is not None
        and minimum is not None
        and minimum > years.value
    ):
        reasons.append(f"JD requires {minimum}+ years; confirmed experience is {years.value:g}")
    clearance = profile.security_clearance
    if (
        requirements.get("clearance_required") is True
        and clearance.state == "known"
        and clearance.value is False
    ):
        reasons.append("JD requires clearance; candidate confirms no clearance")
    return reasons
