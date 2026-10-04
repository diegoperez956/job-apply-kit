from __future__ import annotations

from job_apply_kit.packet import render_packet
from job_apply_kit.profile import Fact
from job_apply_kit.resume_tailor import ResumeBlock, ResumeEvidence


def test_packet_only_reorders_confirmed_evidence_and_jev_is_additive(profile):
    evidence = ResumeEvidence(
        skills=Fact(value=["SQL", "Python"], state="known"),
        experience=[
            ResumeBlock(
                label=Fact(value="Example Project", state="known"),
                bullets=Fact(value=["Built SQL reports.", "Built Python tools."], state="known"),
            ),
            ResumeBlock(
                label=Fact(value="Unverified role", state="requires_confirmation"),
                bullets=Fact(value=["Unverified claim."], state="known"),
            ),
        ],
    )
    before = evidence.model_dump()
    job = {
        "title": "Example Engineer",
        "url": "https://example.invalid/job/1",
        "description": "Python required",
        "location": "Remote",
    }
    packet = render_packet(job, profile, evidence)
    assert packet.index("Built Python tools.") < packet.index("Built SQL reports.")
    assert "Unverified claim" not in packet and "Unverified role" not in packet
    assert "Led [project]" not in packet
    assert evidence.model_dump() == before
    job["requirements"] = {"required_skills": ["SQL", "UnownedSkill"]}
    additive = render_packet(job, profile, evidence)
    assert "Built Python tools." in additive and "Built SQL reports." in additive
    assert "UnownedSkill" not in additive
    assert "human" in additive.lower() and "submit" in additive.lower()
