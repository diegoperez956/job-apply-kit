"""Keyword/title fit scoring and location/comp reachability.

Deliberately simple: token-overlap on the title, substring checks on
location. No embeddings, no ML -- a shortlist you can explain in one
sentence is worth more than a score you can't audit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .profile import CandidateProfile, Period

_WORD_RE = re.compile(r"[a-z0-9]+")

# Multiplier to normalize a comp figure to an annual amount before
# comparing. 2080 = 40hr/week * 52 weeks, the standard full-time-hours
# convention -- not exact for any given job, but consistent and auditable.
_ANNUALIZE: dict[str, int] = {"annual": 1, "monthly": 12, "hourly": 2080}


def _to_annual(amount: int, period: str) -> int:
    return amount * _ANNUALIZE[period]


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def title_fit_score(title: str, target_roles: list[str]) -> float:
    """Jaccard overlap between the posting title's words and the union of
    words across all target role strings. 0.0 if there's no overlap or no
    target roles configured."""
    if not target_roles:
        return 0.0
    title_words = _tokens(title)
    role_words: set[str] = set()
    for role in target_roles:
        role_words |= _tokens(role)
    if not title_words or not role_words:
        return 0.0
    overlap = title_words & role_words
    union = title_words | role_words
    return len(overlap) / len(union)


def location_reachable(location: str, profile: CandidateProfile) -> bool:
    """True if the posting's location string is plausibly reachable given
    the candidate's accepted location modes and geography. Unknown/blank
    location is treated as reachable (can't rule it out, tier routing and
    the human review step are the real filter)."""
    if not location:
        return True

    loc = location.lower()
    mode_fact = profile.location_mode
    modes = [] if mode_fact.state == "requires_confirmation" else mode_fact.value

    if "remote" in loc and "remote" in modes:
        return True

    geo_fact = profile.geography
    geography = [] if geo_fact.state == "requires_confirmation" else geo_fact.value
    for allowed in geography:
        if allowed.lower() in loc or loc in allowed.lower():
            return True

    # No geography configured at all -> can't evaluate, don't filter it out.
    if not geography and not modes:
        return True

    return False


def comp_reachable(
    posting_salary: int | None,
    location_mode: str,
    profile: CandidateProfile,
    *,
    currency: str = "USD",
    period: Period = "annual",
) -> bool | None:
    """True/False if we can compare a posted salary figure against the
    profile's floor for that location mode; None ("unknown", never
    silently treated as reachable or unreachable) when there's nothing
    safe to compare: no posted salary, no confirmed floor for this mode,
    or a currency that doesn't match the floor's -- this module does no
    FX conversion, so a currency mismatch stays neutral rather than
    comparing two different currencies as if they were the same number.
    Pay period IS handled: both figures are normalized to an annual
    amount before comparing, so a $60/hr posting compares correctly
    against an annual floor.
    """
    if posting_salary is None:
        return None
    floor = profile.comp_floor_by_mode.get(location_mode)
    if floor is None or floor.state == "requires_confirmation":
        return None
    floor_value = floor.value
    if currency.strip().upper() != floor_value.currency.strip().upper():
        return None
    return _to_annual(posting_salary, period) >= _to_annual(floor_value.amount, floor_value.period)


@dataclass
class RankedJob:
    title: str
    location: str
    url: str
    fit_score: float
    location_ok: bool
    company: str = ""
    # None ("unknown comp") whenever the posting carries no salary figure
    # or we have nothing safe to compare it to -- see comp_reachable().
    # Left unset (None) rather than dropped so every consumer of a
    # RankedJob has to see the "we don't know" case explicitly labeled,
    # instead of it reading as "comp is fine" by omission.
    comp_ok: bool | None = None


def rank_jobs(postings: list[dict], profile: CandidateProfile) -> list[RankedJob]:
    """Score and sort a list of posting dicts (title, location, url,
    company keys expected; missing keys default to ''). Highest fit first;
    ties broken by location_ok (reachable first).

    A posting may optionally carry salary_amount/salary_currency (default
    USD)/salary_period (default annual) to get a comp_ok verdict via
    comp_reachable() -- see RankedJob.comp_ok. The location mode used to
    pick a comp floor is location_mode if the posting provides one,
    else inferred the same way location_reachable() reads "remote" out
    of the location string; a posting we can't place into a mode gets
    comp_ok=None (unknown), never guessed.
    """
    target_roles = (
        profile.target_roles.value if profile.target_roles.state != "requires_confirmation" else []
    )
    ranked = []
    for p in postings:
        location = p.get("location", "")
        mode = p.get("location_mode") or ("remote" if "remote" in location.lower() else "")
        ranked.append(
            RankedJob(
                title=p.get("title", ""),
                location=location,
                url=p.get("url", ""),
                company=p.get("company", ""),
                fit_score=title_fit_score(p.get("title", ""), target_roles),
                location_ok=location_reachable(location, profile),
                comp_ok=comp_reachable(
                    p.get("salary_amount"),
                    mode,
                    profile,
                    currency=p.get("salary_currency", "USD"),
                    period=p.get("salary_period", "annual"),
                ),
            )
        )
    ranked.sort(key=lambda r: (r.fit_score, r.location_ok), reverse=True)
    return ranked
