from __future__ import annotations

from job_apply_kit.rank import RankedJob
from job_apply_kit.shortlist import render_shortlist


def test_render_shortlist_empty():
    assert "No jobs to show" in render_shortlist([], None)


def test_render_shortlist_includes_prep_pack(profile):
    ranked = [
        RankedJob(
            title="Backend Engineer",
            location="Remote",
            url="https://example.com/job/1",
            fit_score=0.5,
            location_ok=True,
            company="Example Co",
        )
    ]
    md = render_shortlist(ranked, profile)
    assert "Backend Engineer" in md
    assert "Example Co" in md
    assert "SUGGESTION" in md
    assert "Fit rationale" in md
    assert "Pre-drafted screener answers" in md
    # sponsorship_needed is known/False in the base fixture profile
    assert "sponsorship" in md.lower()


def test_render_shortlist_flags_unconfirmed_screener_answer(profile_factory):
    from job_apply_kit.profile import ScreenerAnswer

    p = profile_factory(
        screener_answers=[
            ScreenerAnswer(
                question="Why do you want to work here?",
                answer="unused placeholder",
                state="requires_confirmation",
            )
        ]
    )
    ranked = [
        RankedJob(title="Engineer", location="Remote", url="u", fit_score=0.1, location_ok=True)
    ]
    md = render_shortlist(ranked, p)
    assert "NEEDS CONFIRMATION" in md
    assert "unused placeholder" not in md
