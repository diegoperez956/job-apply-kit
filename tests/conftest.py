from __future__ import annotations

import pytest

from job_apply_kit.profile import (
    Authorization,
    CandidateProfile,
    CompFloor,
    Fact,
    SelfIdPrefs,
)


def make_profile(**overrides) -> CandidateProfile:
    """Fully-confirmed profile (every fact known/preference, nothing
    requires_confirmation), for tests that don't care about that state.
    Pass overrides as raw field kwargs (already-constructed Fact/model
    values)."""
    base = dict(
        target_roles=Fact(value=["Software Engineer", "Backend Engineer"], state="known"),
        seniority=Fact(value="senior", state="known"),
        location_mode=Fact(value=["remote", "hybrid"], state="known"),
        geography=Fact(value=["US-remote", "Austin, TX"], state="known"),
        comp_floor_by_mode={
            "remote": Fact(
                value=CompFloor(amount=150000, currency="USD", period="annual"), state="known"
            ),
            "hybrid": Fact(
                value=CompFloor(amount=160000, currency="USD", period="annual"), state="known"
            ),
        },
        authorizations=Fact(
            value=[Authorization(country="US", status="citizen", sponsorship_required=False)],
            state="known",
        ),
        relocation=Fact(value=False, state="known"),
        relocation_notes=Fact(value=None, state="known"),
        start_date=Fact(value="2_weeks_notice", state="known"),
        non_compete=Fact(value=False, state="known"),
        non_compete_notes=Fact(value=None, state="known"),
        industries_to_avoid=Fact(value=[], state="preference"),
        employer_blacklist=Fact(value=[], state="preference"),
        dealbreakers=Fact(value=[], state="preference"),
        self_id=SelfIdPrefs(
            gender=Fact(value="decline_to_answer", state="preference"),
            race_ethnicity=Fact(value="decline_to_answer", state="preference"),
            veteran_status=Fact(value="decline_to_answer", state="preference"),
            disability_status=Fact(value="decline_to_answer", state="preference"),
        ),
        links=Fact(value={"linkedin": "https://linkedin.com/in/test"}, state="known"),
    )
    base.update(overrides)
    return CandidateProfile(**base)


@pytest.fixture
def profile() -> CandidateProfile:
    return make_profile()


@pytest.fixture
def profile_factory():
    """Fixture form of make_profile(), for tests that need overrides."""
    return make_profile
