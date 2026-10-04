from job_apply_kit.decision_policy import requirement_mismatches
from job_apply_kit.profile import Fact


def test_requirement_rules_use_user_facts_not_a_fixed_years_cutoff(profile_factory):
    experienced = profile_factory(
        experience_years=Fact(value=8, state="known"),
        security_clearance=Fact(value=True, state="known"),
    )
    assert requirement_mismatches({"min_years": 6, "clearance_required": True}, experienced) == []
    newer = profile_factory(
        experience_years=Fact(value=2, state="known"),
        security_clearance=Fact(value=False, state="known"),
    )
    reasons = requirement_mismatches({"min_years": 6, "clearance_required": True}, newer)
    assert len(reasons) == 2
    assert any("6" in reason and "2" in reason for reason in reasons)
    unknown = profile_factory()
    assert requirement_mismatches(None, unknown) == []
    assert requirement_mismatches({"min_years": None, "clearance_required": None}, unknown) == []
    unconfirmed = profile_factory(
        experience_years=Fact(value=1, state="requires_confirmation"),
        security_clearance=Fact(value=False, state="preference"),
    )
    assert requirement_mismatches({"min_years": 6, "clearance_required": True}, unconfirmed) == []
