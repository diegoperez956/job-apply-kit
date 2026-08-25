"""Deterministic label -> profile-fact resolver for application screener
questions.

Rule (the whole point of this module): ambiguous input always resolves to
None. That means a label we can't confidently classify, a label that
matches more than one category (compound questions like "X or Y?"), OR a
fact whose state isn't `known` (see profile.py -- `preference` is an
opinion, not a verified fact; `requires_confirmation` is unverified).
This module never guesses and never invents an answer. Callers must treat
None as "leave blank / ask a human", never as an error to work around.
Use `resolve_reason()` alongside `resolve_answer()` to show *why* a field
came back blank.

One narrow exception to the compound-ambiguity rule (see
_resolve_and_compound): "X and Y?" joining two supported *boolean*
categories with a plain "and" (never "or"/"and/or") resolves to that
shared Yes/No, but only when both clauses resolve AND agree -- e.g.
"authorized to work and willing to relocate?" answers Yes only if both
are true on file. Any disagreement, an unresolvable clause, or any
connector other than a bare "and" stays ambiguous (None).
"""

from __future__ import annotations

import re
from typing import Literal

from .profile import Authorization, CandidateProfile, Fact

FieldType = Literal["text", "boolean"]

# Ordered: first matching category wins when only one matches. Keep
# specific phrases before generic ones so e.g. "sponsorship" doesn't fall
# through to a looser rule.
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("sponsorship", ["sponsorship", "sponsor a visa", "require sponsorship", "visa sponsorship"]),
    ("work_authorization", ["authorized to work", "work authorization", "legally eligible"]),
    ("relocation", ["relocate", "relocation"]),
    ("start_date", ["start date", "available to start", "earliest start", "notice period"]),
    (
        "salary_expectation",
        ["salary", "compensation expectation", "pay expectation", "desired pay"],
    ),
    ("linkedin", ["linkedin"]),
    ("github", ["github"]),
    ("portfolio", ["portfolio", "personal website", "personal site"]),
    ("non_compete", ["non-compete", "non compete", "noncompete"]),
]

# Categories whose resolved value renders as "Yes"/"No" rather than a raw
# string. Every boolean-shaped screener question must render this way --
# never a raw status/enum value (e.g. "citizen") -- so work_authorization
# lives here too; see _resolve_category, which resolves it to a bool.
_BOOLEAN_CATEGORIES = {
    "sponsorship",
    "relocation",
    "non_compete",
    "work_authorization",
    "work_authorization_no_sponsorship",
}

# Categories whose boolean value it's safe to flip in response to a
# negated question ("Are you unwilling to relocate?", "Are you not
# authorized to work in the US?"). Deliberately excludes
# work_authorization_no_sponsorship: that category's own resolution
# already builds in the "without sponsorship" negation (see
# _matches_negated_sponsorship_eligibility), so inverting it again would
# double-negate. Text-valued categories (start_date, salary, links)
# aren't here because "invert" doesn't mean anything for a string -- a
# negated question about one of those is refused (None) instead, never
# guessed.
_NEGATABLE_CATEGORIES = {"sponsorship", "relocation", "non_compete", "work_authorization"}

# Generic negation cues. Deliberately simple substring checks, not NLP --
# this module never guesses, so a phrase it can't confidently read as
# negation just falls through unnegated rather than mis-flip an answer.
_NEGATION_PHRASES = (
    "unwilling",
    "not willing",
    "not authorized",
    "not require",
    "no longer",
    "never",
    "without",
)


def _is_negated(lowered: str) -> bool:
    return any(phrase in lowered for phrase in _NEGATION_PHRASES)


# Compound-question splitting ("X or Y?", "X and Y?"). A label matching a
# supported category in one clause and something else -- a different
# category, or a clause with real content we don't recognize at all -- in
# another clause is ambiguous: we can't tell which clause the form
# actually wants answered. A clause made up only of filler/time words
# (the "now or in the future" boilerplate around a single real question)
# is not a second ask, so it stays unambiguous.
_COMPOUND_SPLIT_RE = re.compile(r"\s+(?:and/or|or|and)\s+")
_COMPOUND_WORD_RE = re.compile(r"[a-z0-9]+")
_COMPOUND_FILLER_WORDS = {
    "a", "an", "the", "is", "are", "to", "of", "in", "on", "for", "you",
    "will", "do", "does", "have", "has", "need", "needs", "require",
    "requires", "now", "future", "other", "than", "current", "one", "any",
    "your", "this", "that", "employer",
}  # fmt: skip


def _segment_categories(segment: str) -> list[str]:
    return [
        category
        for category, keywords in _CATEGORY_KEYWORDS
        if any(kw in segment for kw in keywords)
    ]


def _segment_is_substantive(segment: str) -> bool:
    words = _COMPOUND_WORD_RE.findall(segment)
    return any(w not in _COMPOUND_FILLER_WORDS for w in words)


def _matches_negated_sponsorship_eligibility(lowered: str) -> bool:
    """'Are you legally eligible to work without sponsorship?' (and
    similar phrasing) contains both a sponsorship keyword and a work-auth
    keyword, so the plain keyword scan below sees two categories and
    would (correctly, in the general case) call it ambiguous. But
    "without sponsorship" negates the sponsorship mention -- the actual
    ask is a single, answerable eligibility question. Special-case it
    ahead of the generic scan rather than let it fall out as ambiguous or
    misclassify as the (wrong) plain "sponsorship" category."""
    return (
        "without" in lowered
        and "sponsor" in lowered
        and ("eligible" in lowered or "authorized" in lowered)
    )


def _is_relocation_assistance_qualifier(lowered: str) -> bool:
    """ "Are you willing to relocate without assistance?" / "...without
    relocation assistance?" -- "without <anything>" on a relocation label
    qualifies HOW they'd relocate, not whether they're willing to
    relocate at all, so it must not flip the relocation answer the way
    _is_negated() flips "unwilling to relocate". A candidate unwilling to
    relocate at all is still "No" regardless of assistance -- a
    "without ..." qualifier never flips a No base answer to Yes. A
    candidate willing to relocate doesn't tell us whether they'd do it
    under the qualified condition -- that case is refused (None) in
    resolve_answer rather than asserting "Yes" on a fact we don't have.
    Excludes "unwilling"/"not willing", which are real negations of
    willingness, not a qualifier on how."""
    return "without" in lowered and not any(
        phrase in lowered for phrase in ("unwilling", "not willing")
    )


def classify_label(label: str) -> str | None:
    """Map a free-text form-field label to a known category, or None if
    the label doesn't confidently match exactly one category this module
    handles. A label matching zero or more-than-one category is
    ambiguous -> None; see module docstring."""
    lowered = label.lower()

    if _matches_negated_sponsorship_eligibility(lowered):
        return "work_authorization_no_sponsorship"

    segments = _COMPOUND_SPLIT_RE.split(lowered)
    if len(segments) > 1:
        matched_categories: set[str] = set()
        for segment in segments:
            segment_categories = _segment_categories(segment)
            if segment_categories:
                matched_categories.update(segment_categories)
            elif _segment_is_substantive(segment):
                # a clause with real content that doesn't match any
                # category we handle -- can't tell if it's a second,
                # unsupported ask riding along on "or"/"and".
                return None
        if len(matched_categories) > 1:
            return None
        if len(matched_categories) == 1:
            return next(iter(matched_categories))
        # no segment matched anything and none were substantive -- fall
        # through to the plain whole-label scan below.

    matched = [
        category
        for category, keywords in _CATEGORY_KEYWORDS
        if any(kw in lowered for kw in keywords)
    ]
    if len(matched) == 1:
        return matched[0]
    return None


def _resolved(fact: Fact) -> tuple[object | None, str | None]:
    """Only a `known` fact may be asserted on a screener. Returns
    (value, reason): reason is set (and value is None) whenever the fact
    can't be asserted -- `preference` is an opinion the candidate should
    confirm by hand, `requires_confirmation` is simply unverified."""
    if fact.state == "known":
        return fact.value, None
    if fact.state == "preference":
        return None, "preference — confirm by hand"
    return None, "requires confirmation — not yet verified"


def _authorization_for(
    profile: CandidateProfile, country: str | None
) -> tuple[Authorization | None, str | None]:
    """Find the Authorization entry for `country`. Per Q5: use the target
    country when it's known, else None -- this module never guesses which
    country a screener question is about."""
    if country is None:
        return None, "no target country given"
    entries, reason = _resolved(profile.authorizations)
    if entries is None:
        return None, reason
    country_l = country.strip().lower()
    for entry in entries:
        if entry.country.strip().lower() == country_l:
            return entry, None
    return None, f"no authorization on file for {country!r}"


# Authorization.status values that count as "authorized" for the
# combined "eligible without sponsorship" question. Anything else
# (not_authorized, needs_sponsorship, an unrecognized/typo'd status) is
# conservatively treated as not authorized -- this is a legal-eligibility
# question, so an unknown status must never read as Yes.
_AUTHORIZED_STATUSES = {"citizen", "permanent_resident", "visa_holder", "authorized"}


def _resolve_category(
    category: str,
    profile: CandidateProfile,
    *,
    location_mode: str | None,
    country: str | None,
) -> tuple[object | None, str | None]:
    if category == "sponsorship":
        entry, reason = _authorization_for(profile, country)
        return (None, reason) if entry is None else (entry.sponsorship_required, None)

    if category == "work_authorization":
        # Boolean-shaped question ("Are you authorized to work...?") --
        # resolve to authorized/not, never the raw status string. Reuses
        # the same authorized-statuses check as the combined
        # no-sponsorship category, just without the sponsorship half.
        entry, reason = _authorization_for(profile, country)
        if entry is None:
            return None, reason
        return entry.status.strip().lower() in _AUTHORIZED_STATUSES, None

    if category == "work_authorization_no_sponsorship":
        entry, reason = _authorization_for(profile, country)
        if entry is None:
            return None, reason
        # "eligible to work without sponsorship" is only Yes when BOTH
        # halves hold: actually authorized in-country AND no sponsorship
        # needed. A not_authorized status must never read as Yes just
        # because sponsorship_required happens to be (incorrectly) False
        # on file -- status is the authoritative signal here.
        authorized = entry.status.strip().lower() in _AUTHORIZED_STATUSES
        return (authorized and not entry.sponsorship_required), None

    if category == "relocation":
        return _resolved(profile.relocation)

    if category == "non_compete":
        return _resolved(profile.non_compete)

    if category == "start_date":
        return _resolved(profile.start_date)

    if category == "salary_expectation":
        if location_mode is None:
            return None, "no location mode given"
        floor = profile.comp_floor_by_mode.get(location_mode)
        if floor is None:
            return None, f"no comp floor set for {location_mode!r}"
        comp, reason = _resolved(floor)
        return (None, reason) if comp is None else (comp.amount, None)

    if category in ("linkedin", "github", "portfolio"):
        links, reason = _resolved(profile.links)
        if links is None:
            return None, reason
        link = links.get(category)
        return (None, "no link on file for this category") if link is None else (link, None)

    return None, None


def _stringify(category: str, value: object) -> str:
    if category in _BOOLEAN_CATEGORIES:
        return "Yes" if value else "No"
    return str(value)


def _and_compound_categories(lowered: str) -> tuple[str, str] | None:
    """If `lowered` is exactly two clauses joined by a plain "and" (not
    "or"/"and/or" -- see the ambiguity policy below), and each clause
    matches exactly one *different* supported boolean category, return
    the two category names. None for anything else -- a single "or" (or
    "and/or") compound, more than two clauses, or a clause that doesn't
    match exactly one boolean category, all stay ordinary ambiguous
    labels handled by classify_label."""
    connector = _COMPOUND_SPLIT_RE.search(lowered)
    if connector is None or connector.group().strip() != "and":
        return None
    segments = _COMPOUND_SPLIT_RE.split(lowered)
    if len(segments) != 2:
        return None
    cats: list[str] = []
    for segment in segments:
        segment_categories = _segment_categories(segment)
        if len(segment_categories) != 1 or segment_categories[0] not in _BOOLEAN_CATEGORIES:
            return None
        cats.append(segment_categories[0])
    if cats[0] == cats[1]:
        return None
    return cats[0], cats[1]


def _resolve_and_compound(
    lowered: str,
    profile: CandidateProfile,
    *,
    location_mode: str | None,
    country: str | None,
) -> tuple[str | None, str | None]:
    """Ambiguity-policy carve-out: "X and Y?" compounding two supported
    boolean categories (e.g. work authorization + relocation) resolves
    to that shared Yes/No only when BOTH clauses resolve and agree --
    e.g. "Are you authorized to work in the US and willing to relocate?"
    when both are true. Otherwise (an unresolvable clause, or the two
    clauses disagree) it's still refused as ambiguous. Only called once
    classify_label has already given up on the label as a single
    category."""
    cats = _and_compound_categories(lowered)
    if cats is None:
        return None, "ambiguous label — could not classify"
    values: list[bool] = []
    for cat in cats:
        value, reason = _resolve_category(
            cat, profile, location_mode=location_mode, country=country
        )
        if value is None:
            return None, reason or "no value available for one clause of compound question"
        values.append(bool(value))
    if values[0] != values[1]:
        return None, "compound question — clauses resolve to different answers"
    return ("Yes" if values[0] else "No"), None


def resolve_answer(
    label: str,
    profile: CandidateProfile,
    *,
    location_mode: str | None = None,
    country: str | None = None,
    field_type: FieldType = "text",
) -> str | None:
    """Resolve a screener/form field label to an answer string using only
    profile facts.

    Returns None when: the label is ambiguous (no category match, or a
    compound label matching more than one category), the backing fact
    isn't `known` (a `preference` or `requires_confirmation` fact is never
    asserted -- see profile.py), a work-authorization/sponsorship question
    has no matching `country`, or (salary only) no location_mode was given
    or the profile has no confirmed floor for that mode. Call
    `resolve_reason()` with the same arguments to get a human-readable
    reason for a None result.

    `field_type` currently only affects boolean-shaped categories
    (sponsorship, relocation, non_compete) and is accepted for forward
    compatibility with radio/select vs. free-text fields that phrase
    yes/no differently; both current field types render "Yes"/"No".

    A negated label ("Are you unwilling to relocate?", "...without
    sponsorship?") flips the resolved boolean for a negatable category
    (sponsorship/relocation/non_compete); a negated label on any other
    category is refused (None) rather than guess what "invert" means for
    a string.

    A compound label joining two supported boolean categories with a
    plain "and" (e.g. "authorized to work AND willing to relocate?") is
    an exception to the ambiguity policy: it resolves to that shared
    Yes/No when both clauses resolve and agree, else None. Any other
    compound ("or"/"and/or", or more than two clauses) stays ambiguous.
    """
    lowered = label.lower()
    category = classify_label(label)
    if category is None:
        value, _reason = _resolve_and_compound(
            lowered, profile, location_mode=location_mode, country=country
        )
        return value
    qualifier = category == "relocation" and _is_relocation_assistance_qualifier(lowered)
    negated = (
        category != "work_authorization_no_sponsorship" and not qualifier and _is_negated(lowered)
    )
    if negated and category not in _NEGATABLE_CATEGORIES:
        return None
    value, _reason = _resolve_category(
        category, profile, location_mode=location_mode, country=country
    )
    if value is None:
        return None
    if negated:
        value = not value
    if qualifier and value:
        # willing to relocate in general, but whether they'd do it
        # *without assistance* is a fact we don't have -- refuse rather
        # than assert Yes.
        return None
    return _stringify(category, value)


def resolve_reason(
    label: str,
    profile: CandidateProfile,
    *,
    location_mode: str | None = None,
    country: str | None = None,
    field_type: FieldType = "text",
) -> str | None:
    """Explain why resolve_answer() returned None for this label (with the
    same arguments), or None if it actually returned a value."""
    lowered = label.lower()
    category = classify_label(label)
    if category is None:
        _value, reason = _resolve_and_compound(
            lowered, profile, location_mode=location_mode, country=country
        )
        return reason
    qualifier = category == "relocation" and _is_relocation_assistance_qualifier(lowered)
    negated = (
        category != "work_authorization_no_sponsorship" and not qualifier and _is_negated(lowered)
    )
    if negated and category not in _NEGATABLE_CATEGORIES:
        return "negated question outside a category we can safely invert"
    value, reason = _resolve_category(
        category, profile, location_mode=location_mode, country=country
    )
    if value is None:
        return reason or "no value available"
    if qualifier and value:
        return "relocation assistance qualifier — willingness without assistance unknown"
    return None
