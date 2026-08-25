"""Optional LLM shim.

No SDK dependency: shells out to the `claude` CLI (`claude -p <prompt>`)
if it's on PATH, else returns None and prints a clear notice. Nothing in
this kit requires an LLM -- it's an optional assist (e.g. drafting a
resume bullet phrasing from profile facts), never used for anything that
touches caps, tier routing, or screener answers -- those stay
deterministic (see caps.py, tier.py, answers.py).
"""

from __future__ import annotations

import shutil
import subprocess
import sys


def is_available() -> bool:
    return shutil.which("claude") is not None


def ask(prompt: str, *, timeout: float = 60.0) -> str | None:
    """Run `claude -p <prompt>` and return its stdout, or None if the
    `claude` CLI isn't installed or the call fails. Never raises -- prints
    a one-line notice to stderr instead, since every caller in this kit
    must have a working fallback when no LLM is available."""
    if not is_available():
        print(
            "job_apply_kit.llm: `claude` CLI not found on PATH; skipping LLM assist.",
            file=sys.stderr,
        )
        return None
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"job_apply_kit.llm: `claude -p` failed: {e}", file=sys.stderr)
        return None

    if result.returncode != 0:
        print(
            f"job_apply_kit.llm: `claude -p` exited {result.returncode}: {result.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    return result.stdout.strip()
