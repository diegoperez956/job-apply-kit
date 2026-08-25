"""Render a ranked markdown shortlist with a prep pack per job.

Everything in the prep pack is grounded on profile facts -- nothing here
invents work history or claims. Resume bullets are templated and marked
SUGGESTION because this kit has no access to the candidate's actual
experience; a human fills those in. Screener answers come straight from
answers.resolve_answer() and profile.screener_answers, so anything
unconfirmed shows up as a visible TODO instead of a guessed answer.
"""

from __future__ import annotations

from .answers import resolve_answer, resolve_reason
from .profile import CandidateProfile
from .rank import RankedJob

_STANDARD_SCREENER_LABELS = [
    "Are you authorized to work in this country?",
    "Will you now or in the future require visa sponsorship?",
    "Are you willing to relocate?",
    "What is your earliest start date?",
]


def _fit_rationale(job: RankedJob, profile: CandidateProfile) -> str:
    roles_fact = profile.target_roles
    roles = [] if roles_fact.state == "requires_confirmation" else roles_fact.value
    if job.fit_score <= 0 or not roles:
        return "No title/role-keyword overlap found -- review manually before applying."
    return (
        f"Title overlaps with target roles ({', '.join(roles)}); "
        f"keyword fit score {job.fit_score:.2f}."
    )


def _target_country(profile: CandidateProfile) -> str | None:
    """The country to resolve work-authorization/sponsorship screener
    questions against. Only inferred when unambiguous: exactly one
    confirmed authorization on file. Multiple countries on file -> None,
    don't guess which one a given posting is asking about."""
    auth = profile.authorizations
    if auth.state != "known" or len(auth.value) != 1:
        return None
    return auth.value[0].country


def _prep_pack(job: RankedJob, profile: CandidateProfile) -> str:
    location_note = "reachable" if job.location_ok else "NEEDS REVIEW -- outside configured geo"
    country = _target_country(profile)
    lines = [
        "**Fit rationale:** " + _fit_rationale(job, profile),
        f"**Location:** {job.location or 'unspecified'} ({location_note})",
    ]

    lines.append("\n**Suggested resume bullets (SUGGESTION -- edit before use):**")
    seniority = "TARGET_SENIORITY"
    if profile.seniority.state != "requires_confirmation":
        seniority = profile.seniority.value
    lines.append(
        f"- SUGGESTION: Led [project] as a {seniority} contributor, delivering [measurable outcome]"
    )
    lines.append(
        "- SUGGESTION: [Add a bullet tying your actual experience to this posting's requirements.]"
    )

    lines.append("\n**Pre-drafted screener answers:**")
    for label in _STANDARD_SCREENER_LABELS:
        answer = resolve_answer(label, profile, country=country)
        if answer is not None:
            lines.append(f"- {label} -> {answer}")
        else:
            reason = resolve_reason(label, profile, country=country) or "see profile"
            lines.append(f"- {label} -> NEEDS CONFIRMATION ({reason})")

    for sa in profile.screener_answers:
        if sa.state == "known":
            lines.append(f"- {sa.question} -> {sa.answer}")
        elif sa.state == "preference":
            lines.append(f"- {sa.question} -> NEEDS CONFIRMATION (preference — confirm by hand)")
        else:
            lines.append(f"- {sa.question} -> NEEDS CONFIRMATION (see profile)")

    return "\n".join(lines)


def render_shortlist(ranked: list[RankedJob], profile: CandidateProfile) -> str:
    """Render the full shortlist as a markdown document, highest fit first."""
    if not ranked:
        return "# Job Shortlist\n\nNo jobs to show.\n"

    out = ["# Job Shortlist\n"]
    for i, job in enumerate(ranked, start=1):
        header = f"## {i}. {job.title}"
        if job.company:
            header += f" -- {job.company}"
        out.append(header)
        out.append(f"{job.url}\n")
        out.append(_prep_pack(job, profile))
        out.append("")
    return "\n".join(out)
