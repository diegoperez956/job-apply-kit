"""Probe a list of candidate Greenhouse board-token slugs and report which
ones exist and have a job title matching a keyword.

Useful when you know a company's name but not its Greenhouse slug --
guess a few variants ("acme", "acme-inc", "acmehq") and let this find
the live one.

Usage:
    python -m job_apply_kit.sources.probe_boards --keyword "engineer" \
        acme acme-inc acmehq
"""

from __future__ import annotations

import argparse
import sys

from .greenhouse import GreenhouseError, fetch_jobs


def probe(slugs: list[str], keyword: str | None) -> int:
    """Print a report line per slug. Returns process exit code (0 if at
    least one slug resolved to a board with jobs, else 1)."""
    found_any = False
    for slug in slugs:
        try:
            jobs = fetch_jobs(slug)
        except GreenhouseError as e:
            print(f"{slug}: NOT FOUND ({e})")
            continue

        matches = jobs
        if keyword:
            needle = keyword.lower()
            matches = [j for j in jobs if needle in j.title.lower()]

        found_any = found_any or bool(jobs)
        print(f"{slug}: {len(jobs)} open jobs, {len(matches)} match {keyword!r}")
        for j in matches[:10]:
            print(f"  - {j.title} ({j.location}) {j.absolute_url}")

    return 0 if found_any else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="+", help="candidate board_token values to try")
    parser.add_argument("--keyword", default=None, help="only report jobs with this in the title")
    args = parser.parse_args(argv)
    return probe(args.slugs, args.keyword)


if __name__ == "__main__":
    sys.exit(main())
