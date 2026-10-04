"""Validate and install user-edited YAML evidence using the tailoring schema."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from .integrations import IntegrationError
from .profile import load_profile
from .resume_tailor import load_evidence


def update_resume(source: Path, target: Path, profile: Path, *, check: bool = False) -> int:
    load_profile(profile)
    if not source.is_file():
        raise IntegrationError("resume source must be an existing YAML evidence file")
    evidence = load_evidence(source, required=True)
    pending = int(evidence.skills.state == "requires_confirmation") + sum(
        int(fact.state == "requires_confirmation")
        for block in evidence.experience
        for fact in (block.label, block.bullets)
    )
    if check:
        print(f"resume evidence valid; {pending} fact(s) require confirmation; nothing changed")
        return 0
    if (
        target.name.endswith(".example.yaml")
        or target.is_symlink()
        or target.resolve() == profile.resolve()
    ):
        raise IntegrationError(
            "resume destination must be private evidence, not profile/example/link"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    # Replace atomically; readers see either the old or the validated new source.
    # No extraction, rewriting, or promotion of Fact states takes place.
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".resume-update-")
    try:
        with os.fdopen(fd, "w") as stream:
            # Serialize the validated snapshot, not a second read of a possibly edited draft.
            yaml.safe_dump(evidence.model_dump(mode="json"), stream, sort_keys=False)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(f"resume source updated; {pending} fact(s) require confirmation")
    print("Future discover/packet runs use this evidence; regenerate existing packets.")
    return 0
