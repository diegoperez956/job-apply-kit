from __future__ import annotations

import pytest

from job_apply_kit.answers import classify_label, resolve_answer, resolve_reason
from job_apply_kit.profile import Authorization, Fact

# Q1: negation- and compound-aware classification. Each label maps to the
# single category it should resolve to, or None if it's genuinely
# ambiguous (no match, or matches more than one category).
_TRICKY_LABELS = [
    # "without sponsorship" negates the sponsorship keyword -- this is a
    # work-authorization eligibility question, not a sponsorship one.
    ("Are you legally eligible to work without sponsorship?", "work_authorization_no_sponsorship"),
    # plain sponsorship phrasing, still a single category despite "or".
    ("Will you now or in the future require visa sponsorship?", "sponsorship"),
    # "other than" doesn't introduce a second category here.
    (
        "Are you authorized to work in the U.S. for any employer other than your current one?",
        "work_authorization",
    ),
    # compound "or" spanning two real categories -> ambiguous.
    ("Are you willing to relocate or will you require visa sponsorship?", None),
    ("Do you have a non-compete or need visa sponsorship?", None),
    # compound "or" mixing a supported category with an unrecognized one
    # -> still ambiguous, even though only one clause matches a category.
    ("Are you willing to relocate or travel 75%?", None),
    ("Are you willing to relocate and/or travel 75%?", None),
    # unrelated -> no match at all.
    ("What's your favorite color?", None),
]


@pytest.mark.parametrize("label,expected", _TRICKY_LABELS)
def test_classify_label_tricky_table(label, expected):
    assert classify_label(label) == expected


def test_resolve_answer_ambiguous_label_is_none(profile):
    assert resolve_answer("What's your favorite color?", profile) is None


def test_resolve_answer_known_fact(profile):
    assert resolve_answer("Are you willing to relocate?", profile) == "No"
    assert resolve_answer("Will you require sponsorship?", profile, country="US") == "No"
    assert resolve_answer("LinkedIn URL", profile) == "https://linkedin.com/in/test"


def test_resolve_answer_negated_sponsorship_eligibility(profile):
    label = "Are you legally eligible to work without sponsorship?"
    assert resolve_answer(label, profile, country="US") == "Yes"


def test_resolve_answer_requires_confirmation_is_none(profile_factory):
    p = profile_factory(
        authorizations=Fact(
            value=[Authorization(country="US", status="citizen", sponsorship_required=False)],
            state="requires_confirmation",
        )
    )
    assert resolve_answer("Are you authorized to work in this country?", p, country="US") is None
    assert resolve_reason("Are you authorized to work in this country?", p, country="US") == (
        "requires confirmation — not yet verified"
    )


def test_resolve_answer_preference_state_is_none_with_reason(profile_factory):
    p = profile_factory(relocation=Fact(value=True, state="preference"))
    assert resolve_answer("Are you willing to relocate?", p) is None
    assert resolve_reason("Are you willing to relocate?", p) == "preference — confirm by hand"


def test_resolve_answer_no_country_given_is_none(profile):
    assert resolve_answer("Will you require sponsorship?", profile) is None
    assert resolve_reason("Will you require sponsorship?", profile) == "no target country given"


def test_resolve_answer_unknown_country_is_none(profile):
    assert resolve_answer("Will you require sponsorship?", profile, country="DE") is None
    assert resolve_reason("Will you require sponsorship?", profile, country="DE") == (
        "no authorization on file for 'DE'"
    )


def test_resolve_reason_ambiguous_label(profile):
    reason = resolve_reason("What's your favorite color?", profile)
    assert reason == "ambiguous label — could not classify"


def test_resolve_reason_none_when_answer_present(profile):
    assert resolve_reason("Are you willing to relocate?", profile) is None


def test_resolve_answer_salary_needs_location_mode(profile):
    assert resolve_answer("Desired salary", profile) is None
    assert resolve_answer("Desired salary", profile, location_mode="remote") == "150000"
    assert resolve_answer("Desired salary", profile, location_mode="onsite") is None


# Q1 repros: negation, compound ambiguity, authorization consistency.


def test_resolve_answer_negated_relocation_inverts(profile):
    # profile fixture has relocation=False (known) -- "unwilling" negates
    # the question, so the correct answer is "Yes" (yes, unwilling).
    assert resolve_answer("Are you unwilling to relocate?", profile) == "Yes"
    assert resolve_answer("Are you not willing to relocate?", profile) == "Yes"


def test_resolve_answer_negated_relocation_true_case(profile_factory):
    p = profile_factory(relocation=Fact(value=True, state="known"))
    assert resolve_answer("Are you unwilling to relocate?", p) == "No"


def test_resolve_answer_compound_or_mixing_known_and_unknown_is_none(profile):
    assert resolve_answer("Are you willing to relocate or travel 75%?", profile) is None
    assert resolve_reason("Are you willing to relocate or travel 75%?", profile) == (
        "ambiguous label — could not classify"
    )


def test_resolve_answer_negated_non_negatable_category_is_none(profile_factory):
    # "never" on a text-valued category (work_authorization, raw status
    # string) can't be sensibly inverted -- refuse rather than guess.
    p = profile_factory(start_date=Fact(value="immediate", state="known"))
    assert resolve_answer("Will you never require a start date extension?", p) is None


def test_resolve_answer_authorization_requires_authorized_status_and_no_sponsorship(
    profile_factory,
):
    # authorized AND sponsorship_required=False -> Yes
    p_yes = profile_factory(
        authorizations=Fact(
            value=[Authorization(country="US", status="citizen", sponsorship_required=False)],
            state="known",
        )
    )
    assert (
        resolve_answer("Are you legally eligible to work without sponsorship?", p_yes, country="US")
        == "Yes"
    )

    # not_authorized status, even with sponsorship_required (incorrectly)
    # False on file, must still read No -- status is authoritative.
    p_no = profile_factory(
        authorizations=Fact(
            value=[
                Authorization(country="US", status="not_authorized", sponsorship_required=False)
            ],
            state="known",
        )
    )
    assert (
        resolve_answer("Are you legally eligible to work without sponsorship?", p_no, country="US")
        == "No"
    )

    # authorized but sponsorship_required=True -> No
    p_needs_sponsor = profile_factory(
        authorizations=Fact(
            value=[Authorization(country="US", status="visa_holder", sponsorship_required=True)],
            state="known",
        )
    )
    assert (
        resolve_answer(
            "Are you legally eligible to work without sponsorship?",
            p_needs_sponsor,
            country="US",
        )
        == "No"
    )


def test_resolve_answer_relocation_assistance_qualifier_not_negation(profile):
    # profile fixture has relocation=False -- "without relocation
    # assistance" is a qualifier on HOW, not a negation of willingness,
    # so an unwilling-to-relocate candidate is still "No".
    label = "Are you willing to relocate without relocation assistance?"
    assert resolve_answer(label, profile) == "No"


def test_resolve_answer_relocation_assistance_qualifier_unknown_when_willing(profile_factory):
    # willing to relocate in general, but whether they'd do it *without*
    # assistance is a fact this profile doesn't have -- refuse (None)
    # rather than assert Yes.
    p = profile_factory(relocation=Fact(value=True, state="known"))
    label = "Are you willing to relocate without relocation assistance?"
    assert resolve_answer(label, p) is None
    assert resolve_reason(label, p) == (
        "relocation assistance qualifier — willingness without assistance unknown"
    )


def test_resolve_answer_not_authorized_is_boolean_inversion(profile):
    # profile fixture is authorized (status="citizen") -- "not
    # authorized" negates the plain work_authorization category, and the
    # result must be a Yes/No boolean, never the raw status string.
    assert resolve_answer("Are you not authorized to work in the US?", profile, country="US") == (
        "No"
    )


def test_resolve_answer_work_authorization_renders_boolean_not_raw_status(profile):
    # unnegated, plain work_authorization question also renders Yes/No,
    # never the raw enum status value ("citizen").
    assert resolve_answer("Are you authorized to work in this country?", profile, country="US") == (
        "Yes"
    )


def test_resolve_answer_relocate_and_or_travel_is_none(profile):
    assert resolve_answer("Are you willing to relocate and/or travel 75%?", profile) is None


# Repro: "without <qualifier>" (any qualifier, not just the exact phrase
# "relocation assistance") never flips a No base answer to Yes.


def test_resolve_answer_relocate_without_assistance_stays_no_when_base_is_no(profile):
    # profile fixture: relocation=False. "without assistance" qualifies
    # HOW, not whether -- an unwilling candidate is still "No".
    label = "Are you willing to relocate without assistance?"
    assert resolve_answer(label, profile) == "No"


# Repro: negated question about a negative fact inverts correctly --
# boolean answer = category_value XOR question_negated.


def test_resolve_answer_negated_sponsorship_question_inverts(profile_factory):
    p = profile_factory(
        authorizations=Fact(
            value=[Authorization(country="US", status="citizen", sponsorship_required=False)],
            state="known",
        )
    )
    assert resolve_answer("Will you not require sponsorship?", p, country="US") == "Yes"


# Q1 repro: compound "X and Y?" mixing two supported boolean categories
# is ambiguous UNLESS both clauses resolve to the same Yes/No AND the
# connector is a plain "and" -- then that shared value. 12-row table
# covering: matching "and" (agree/disagree), "or" (never resolved even
# when clauses would agree), "and/or", and 3+ clauses.


_AND_COMPOUND_LABEL = "Are you authorized to work in the US and willing to relocate?"
_OR_COMPOUND_LABEL = "Are you authorized to work in the US or willing to relocate?"
_AND_OR_COMPOUND_LABEL = "Are you authorized to work in the US and/or willing to relocate?"
_TRIPLE_AND_LABEL = (
    "Are you authorized to work in the US and willing to relocate and require sponsorship?"
)


@pytest.mark.parametrize(
    "label,relocation,status,sponsorship_required,expected",
    [
        # "and", both clauses True -> Yes.
        (_AND_COMPOUND_LABEL, True, "citizen", False, "Yes"),
        # "and", both clauses False -> No.
        (_AND_COMPOUND_LABEL, False, "not_authorized", True, "No"),
        # "and", clauses disagree (auth True, relocation False) -> None.
        (_AND_COMPOUND_LABEL, False, "citizen", False, None),
        # "and", clauses disagree (auth False, relocation True) -> None.
        (_AND_COMPOUND_LABEL, True, "not_authorized", True, None),
        # "or" never gets the "and" carve-out, even when clauses agree.
        (_OR_COMPOUND_LABEL, True, "citizen", False, None),
        (_OR_COMPOUND_LABEL, False, "not_authorized", True, None),
        # "and/or" is not a plain "and" either -> always ambiguous.
        (_AND_OR_COMPOUND_LABEL, True, "citizen", False, None),
        (_AND_OR_COMPOUND_LABEL, False, "not_authorized", True, None),
        # three clauses ("and" x2) -> not a two-clause compound -> ambiguous.
        (_TRIPLE_AND_LABEL, True, "citizen", False, None),
        (_TRIPLE_AND_LABEL, False, "not_authorized", True, None),
        # single non-compound labels, included for contrast -- always resolve.
        ("Are you authorized to work in this country?", True, "citizen", False, "Yes"),
        ("Are you willing to relocate?", True, "citizen", False, "Yes"),
    ],
)
def test_compound_and_ambiguity_policy_table(
    profile_factory, label, relocation, status, sponsorship_required, expected
):
    p = profile_factory(
        relocation=Fact(value=relocation, state="known"),
        authorizations=Fact(
            value=[
                Authorization(
                    country="US", status=status, sponsorship_required=sponsorship_required
                )
            ],
            state="known",
        ),
    )
    assert resolve_answer(label, p, country="US") == expected
