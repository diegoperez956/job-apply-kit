"""Prepare a Markdown packet. Browser interaction and submit belong to a human."""

from __future__ import annotations

from html import escape
from urllib.parse import urlsplit

from .answers import resolve_answer, resolve_reason
from .decision_policy import requirement_mismatches
from .integrations import IntegrationError
from .profile import CandidateProfile
from .resume_tailor import ResumeEvidence, reorder_evidence


def render_packet(
    job: dict, profile: CandidateProfile, evidence: ResumeEvidence, *, simplify: bool = False
) -> str:
    url = job.get("url") or ""
    if urlsplit(url).scheme != "https" or not urlsplit(url).hostname:
        raise IntegrationError("packets require an HTTPS job URL")
    tailored = reorder_evidence(evidence, job)
    lines = [
        f"# Application packet: {escape(job.get('title') or 'Job')}",
        "",
        url,
        "",
        f"Location: {escape(job.get('location') or 'unspecified')}",
        "A human verifies every claim, reviews every field, and clicks submit.",
        "",
        "## Confirmed resume evidence (reordered only)",
    ]
    if job.get("demo"):
        lines.insert(2, "**DEMO ONLY: fictional or mocked data; do not use to apply.**")
    if tailored.skills.state == "known" and tailored.skills.value:
        lines.append("Skills: " + ", ".join(escape(s) for s in tailored.skills.value))
    included = False
    for block in tailored.experience:
        if block.label.state != "known" or block.bullets.state != "known":
            continue
        included = True
        lines.append("\n### " + escape(block.label.value))
        lines.extend("- " + escape(text) for text in block.bullets.value)
    if not included:
        lines.append("No confirmed work bullets supplied. Attach your own reviewed resume.")
    reasons = requirement_mismatches(job.get("requirements"), profile)
    lines.append("\n## Requirements to verify (not candidate facts)")
    lines.extend("- NEEDS REVIEW: " + reason for reason in reasons)
    if not reasons:
        lines.append("No known years/clearance mismatch; this is not an eligibility guarantee.")
    lines.append("\n## Screener answers (profile facts only)")
    auth = profile.authorizations
    country = auth.value[0].country if auth.state == "known" and len(auth.value) == 1 else None
    for label in [
        "Are you authorized to work in this country?",
        "Will you now or in the future require visa sponsorship?",
        "Are you willing to relocate?",
        "What is your earliest start date?",
    ]:
        answer = resolve_answer(label, profile, country=country)
        answer = (
            answer
            if answer is not None
            else (
                "NEEDS CONFIRMATION: "
                + (resolve_reason(label, profile, country=country) or "unknown")
            )
        )
        lines.append(f"- {label} -> {escape(answer)}")
    for answer in profile.screener_answers:
        text = answer.answer if answer.state == "known" else "NEEDS CONFIRMATION"
        lines.append(f"- {escape(answer.question)} -> {escape(text)}")
    lines.append("\n## Human handoff")
    if simplify:
        lines.extend(
            [
                "1. Install Simplify Copilot from https://simplify.jobs/copilot "
                "in your own browser.",
                "2. Read https://simplify.jobs/terms; sign in yourself. "
                "Never share cookies or profiles.",
                "3. Open the job URL yourself; let the extension fill supported fields.",
                "4. Verify EVERY field against confirmed facts, including uploads and self-ID.",
                "5. Stop on CAPTCHA, login challenge, logout, 401/403/429, or uncertain answers.",
                "6. Only a human clicks submit. No auto-submit, credential or protection bypass.",
                "A cap slot was reserved for this handoff, not proof of a submitted application.",
            ]
        )
    else:
        lines.append("Open the employer page yourself, fill the form, review, and submit by hand.")
    return "\n".join(lines) + "\n"
