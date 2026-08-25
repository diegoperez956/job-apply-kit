from __future__ import annotations

from job_apply_kit.rank import comp_reachable, location_reachable, rank_jobs, title_fit_score


def test_title_fit_score_full_overlap():
    assert title_fit_score("Backend Engineer", ["Backend Engineer"]) == 1.0


def test_title_fit_score_no_target_roles_is_zero():
    assert title_fit_score("Backend Engineer", []) == 0.0


def test_title_fit_score_no_overlap_is_zero():
    assert title_fit_score("Barista", ["Backend Engineer"]) == 0.0


def test_location_reachable_remote_match(profile):
    assert location_reachable("Remote - US", profile) is True


def test_location_reachable_geography_substring_match(profile):
    assert location_reachable("Austin, TX", profile) is True


def test_location_reachable_blank_location_is_true(profile):
    assert location_reachable("", profile) is True


def test_location_reachable_unmatched_is_false(profile):
    assert location_reachable("Onsite - Tokyo", profile) is False


def test_location_reachable_no_geo_configured_is_true(profile_factory):
    from job_apply_kit.profile import Fact

    p = profile_factory(
        location_mode=Fact(value=[], state="requires_confirmation"),
        geography=Fact(value=[], state="requires_confirmation"),
    )
    assert location_reachable("Onsite - Tokyo", p) is True


def test_comp_reachable_none_without_salary(profile):
    assert comp_reachable(None, "remote", profile) is None


def test_comp_reachable_none_without_confirmed_floor(profile_factory):
    p = profile_factory(comp_floor_by_mode={})
    assert comp_reachable(200000, "remote", p) is None


def test_comp_reachable_true_above_floor(profile):
    assert comp_reachable(200000, "remote", profile) is True


def test_comp_reachable_false_below_floor(profile):
    assert comp_reachable(50000, "remote", profile) is False


def test_rank_jobs_sorts_best_fit_first(profile):
    postings = [
        {"title": "Marketing Manager", "location": "Remote", "url": "u1", "company": "A"},
        {"title": "Backend Engineer", "location": "Remote", "url": "u2", "company": "B"},
    ]
    ranked = rank_jobs(postings, profile)
    assert ranked[0].title == "Backend Engineer"
    assert ranked[0].fit_score > ranked[1].fit_score


def test_comp_reachable_currency_mismatch_is_none(profile):
    # profile floor is USD -- a EUR posting figure can't be safely
    # compared without FX conversion, so it stays neutral/unknown.
    assert comp_reachable(200000, "remote", profile, currency="EUR") is None


def test_comp_reachable_hourly_period_normalized_to_annual(profile):
    # profile floor for "remote" is $150000/year. $100/hr * 2080 =
    # $208000/year, comfortably above -> True.
    assert comp_reachable(100, "remote", profile, period="hourly") is True
    # $50/hr * 2080 = $104000/year, below the floor -> False.
    assert comp_reachable(50, "remote", profile, period="hourly") is False


def test_comp_reachable_monthly_period_normalized_to_annual(profile):
    # $13000/mo * 12 = $156000/year, above the $150000 floor -> True.
    assert comp_reachable(13000, "remote", profile, period="monthly") is True


def test_rank_jobs_wires_comp_ok_via_comp_reachable(profile):
    postings = [
        {
            "title": "Backend Engineer",
            "location": "Remote",
            "url": "u1",
            "company": "A",
            "salary_amount": 200000,
        },
        {
            "title": "Backend Engineer",
            "location": "Remote",
            "url": "u2",
            "company": "B",
            # no salary at all -> unknown, labeled None
        },
        {
            "title": "Backend Engineer",
            "location": "Remote",
            "url": "u3",
            "company": "C",
            "salary_amount": 200000,
            "salary_currency": "EUR",  # mismatched currency -> unknown
        },
    ]
    ranked = {r.url: r for r in rank_jobs(postings, profile)}
    assert ranked["u1"].comp_ok is True
    assert ranked["u2"].comp_ok is None
    assert ranked["u3"].comp_ok is None


def test_rank_jobs_defaults_missing_fields():
    from job_apply_kit.profile import Fact

    class _StubProfile:
        target_roles = Fact(value=[], state="requires_confirmation")
        location_mode = Fact(value=[], state="requires_confirmation")
        geography = Fact(value=[], state="requires_confirmation")

    ranked = rank_jobs([{}], _StubProfile())
    assert ranked[0].title == ""
    assert ranked[0].company == ""
