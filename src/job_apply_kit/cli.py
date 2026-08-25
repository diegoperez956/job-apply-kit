"""job-apply-kit CLI. Every command here is deterministic -- ranking,
tiering, and caps enforcement never touch an LLM (see llm.py/answers.py
for why). This module claims exactly the commands it implements; keep
README's CLI section in sync with this file, not the other way around.

Console script name: job-apply-kit (see pyproject.toml [project.scripts]).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .caps import DEFAULT_DB_PATH, CapsLedger, load_caps_from_env, normalize_company
from .profile import ProfileError, load_profile, unconfirmed_facts
from .rank import RankedJob, rank_jobs
from .shortlist import render_shortlist
from .sources.greenhouse import GreenhouseError, fetch_jobs
from .sources.probe_boards import probe as probe_boards_run
from .tier import TierConfigError, detect_tier, load_tier_overrides

DEFAULT_PROFILE_PATH = Path("profile/candidate_profile.yaml")
DEFAULT_BOARDS_PATH = Path("config/boards.yaml")
DEFAULT_TIER_OVERRIDES_PATH = Path("config/tier_overrides.yaml")
DEFAULT_TIER_OVERRIDES_LOCAL_PATH = Path("config/tier_overrides.local.yaml")
DEFAULT_BLACKLIST_PATH = Path("config/blacklist.yaml")
DEFAULT_DISCOVER_OUT = Path("artifacts/ranked_jobs.jsonl")


class ConfigStructureError(ValueError):
    """A config file's top-level shape doesn't match what's documented
    for it (e.g. a `- x` YAML list where a mapping is required)."""


def _require_mapping(raw: object, source: str) -> dict:
    if not isinstance(raw, dict):
        raise ConfigStructureError(
            f"{source}: expected a YAML mapping at the top level, got {type(raw).__name__}"
        )
    return raw


def _load_merged_tier_overrides() -> dict:
    """config/tier_overrides.yaml (shared, committed) with
    config/tier_overrides.local.yaml (personal, gitignored -- see P1)
    merged on top."""
    overrides = load_tier_overrides(DEFAULT_TIER_OVERRIDES_PATH)
    overrides.update(load_tier_overrides(DEFAULT_TIER_OVERRIDES_LOCAL_PATH))
    return overrides


def _load_blacklisted_companies(path: Path) -> tuple[set[str], set[str]]:
    """config/blacklist.yaml's `companies` list -- personal, gitignored,
    optional (see config/blacklist.example.yaml). Missing file -> nothing
    blacklisted.

    Returns (names, domains). Name entries are folded with
    normalize_company() -- the same casefold/legal-suffix/punctuation
    normalization caps.py's ledger keys use -- so "Blocked Co" and
    "blocked-co" are the same entry. A dotted entry ("exampleco.io") is
    ambiguous between "a domain" and "a display name that happens to
    contain a dot", so it's added to BOTH sets: as a lowercase domain
    (matched by host suffix, see _is_blacklisted) and as a
    normalize_company()'d name (so it also blocks a board's display name
    "Exampleco.io", which normalizes the same way).
    """
    if not path.exists():
        return set(), set()
    raw = yaml.safe_load(path.read_text())
    raw = _require_mapping(raw if raw is not None else {}, str(path))
    companies = raw.get("companies", [])
    if not isinstance(companies, list):
        raise ConfigStructureError(f"{path}: 'companies' must be a list")
    names: set[str] = set()
    domains: set[str] = set()
    for c in companies:
        entry = str(c).strip().lower()
        if "." in entry:
            domains.add(entry)
        names.add(normalize_company(entry))
    return names, domains


def _is_blacklisted(
    company: str,
    company_name: str | None,
    url: str,
    blacklisted_names: set[str],
    blacklisted_domains: set[str],
) -> bool:
    """True if the board token, the company's display name (when the
    board API exposes one), or the posting's URL host matches a
    blacklist entry -- covers "blacklist by company name" and
    "blacklist by ATS/company domain". Name matching is normalized on
    both sides (see _load_blacklisted_companies); domain matching is a
    host-suffix check (exact host, or a subdomain of it) -- never a bare
    substring, so a blacklisted "acme.com" must not match "notacme.com"."""
    candidates = {normalize_company(company)}
    if company_name:
        candidates.add(normalize_company(company_name))
    if candidates & blacklisted_names:
        return True
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and any(host == d or host.endswith("." + d) for d in blacklisted_domains)


def cmd_interview_check(args: argparse.Namespace) -> int:
    try:
        profile = load_profile(args.profile)
    except ProfileError as e:
        print(f"invalid profile: {e}", file=sys.stderr)
        return 1
    unconfirmed = unconfirmed_facts(profile)
    print(f"profile OK: {args.profile}")
    if unconfirmed:
        print(f"{len(unconfirmed)} fact(s) still requires_confirmation:")
        for name in unconfirmed:
            print(f"  - {name}")
    else:
        print("all facts confirmed")
    return 0


def cmd_probe_boards(args: argparse.Namespace) -> int:
    return probe_boards_run(args.slugs, args.keyword)


def cmd_discover(args: argparse.Namespace) -> int:
    try:
        profile = load_profile(args.profile)
    except ProfileError as e:
        print(f"invalid profile: {e}", file=sys.stderr)
        return 1

    boards_path = Path(args.boards)
    if not boards_path.exists():
        print(
            f"no boards config at {boards_path} (copy config/boards.example.yaml)", file=sys.stderr
        )
        return 1
    boards_raw = _require_mapping(yaml.safe_load(boards_path.read_text()), str(boards_path))
    greenhouse_entries = boards_raw.get("greenhouse", [])
    if not isinstance(greenhouse_entries, list):
        raise ConfigStructureError(f"{boards_path}: 'greenhouse' must be a list")
    tokens = []
    for entry in greenhouse_entries:
        if not isinstance(entry, dict) or "board_token" not in entry:
            raise ConfigStructureError(
                f"{boards_path}: each greenhouse entry must be a mapping with 'board_token'"
            )
        tokens.append(entry["board_token"])
    if not tokens:
        print(f"no greenhouse.board_token entries in {boards_path}", file=sys.stderr)
        return 1

    overrides = _load_merged_tier_overrides()
    blacklisted_names, blacklisted_domains = _load_blacklisted_companies(DEFAULT_BLACKLIST_PATH)
    blacklisted_names |= {normalize_company(c) for c in profile.employer_blacklist.value}
    postings: list[dict] = []
    for token in tokens:
        try:
            jobs = fetch_jobs(token)
        except GreenhouseError as e:
            print(f"skipping board {token!r}: {e}", file=sys.stderr)
            continue
        for j in jobs:
            postings.append(
                {
                    "title": j.title,
                    "location": j.location,
                    "url": j.absolute_url,
                    "company": token,
                    "company_name": j.company_name,
                    "salary_amount": j.salary_amount,
                    "salary_currency": j.salary_currency,
                    "salary_period": j.salary_period,
                }
            )

    if blacklisted_names or blacklisted_domains:
        before = len(postings)
        postings = [
            p
            for p in postings
            if not _is_blacklisted(
                p["company"],
                p.get("company_name"),
                p["url"],
                blacklisted_names,
                blacklisted_domains,
            )
        ]
        skipped = before - len(postings)
        if skipped:
            print(f"skipped {skipped} blacklisted posting(s)", file=sys.stderr)

    ranked = rank_jobs(postings, profile)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for job in ranked:
            row = {
                "title": job.title,
                "location": job.location,
                "url": job.url,
                "company": job.company,
                "fit_score": job.fit_score,
                "location_ok": job.location_ok,
                "comp_ok": job.comp_ok,
                "tier": detect_tier(job.url, overrides),
            }
            f.write(json.dumps(row) + "\n")
    print(f"wrote {len(ranked)} ranked job(s) -> {out_path}")
    return 0


def cmd_shortlist(args: argparse.Namespace) -> int:
    try:
        profile = load_profile(args.profile)
    except ProfileError as e:
        print(f"invalid profile: {e}", file=sys.stderr)
        return 1

    jobs_path = Path(args.jobs)
    if not jobs_path.exists():
        print(f"no such jobs file: {jobs_path} (run `discover` first)", file=sys.stderr)
        return 1

    ranked = []
    for line in jobs_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        ranked.append(
            RankedJob(
                title=row.get("title", ""),
                location=row.get("location", ""),
                url=row.get("url", ""),
                fit_score=row.get("fit_score", 0.0),
                location_ok=row.get("location_ok", True),
                company=row.get("company", ""),
                comp_ok=row.get("comp_ok"),
            )
        )

    md = render_shortlist(ranked, profile)
    if args.out:
        Path(args.out).write_text(md)
        print(f"wrote shortlist -> {args.out}")
    else:
        print(md)
    return 0


def cmd_caps_status(args: argparse.Namespace) -> int:
    config = load_caps_from_env()
    with CapsLedger(args.db, config=config) as ledger:
        status = ledger.status(companies=args.company or None)
    print(json.dumps(status, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-apply-kit")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("interview-check", help="validate profile/candidate_profile.yaml")
    p.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH))
    p.set_defaults(func=cmd_interview_check)

    p = sub.add_parser("probe-boards", help="probe candidate Greenhouse board slugs")
    p.add_argument("slugs", nargs="+", help="candidate board_token values to try")
    p.add_argument("--keyword", default=None, help="only report jobs with this in the title")
    p.set_defaults(func=cmd_probe_boards)

    p = sub.add_parser(
        "discover", help="fetch configured Greenhouse boards, rank, tier, write JSONL"
    )
    p.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH))
    p.add_argument("--boards", default=str(DEFAULT_BOARDS_PATH))
    p.add_argument("--out", default=str(DEFAULT_DISCOVER_OUT))
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("shortlist", help="render a markdown shortlist from a `discover` JSONL file")
    p.add_argument("jobs", help="JSONL file produced by `discover`")
    p.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH))
    p.add_argument("--out", default=None, help="write to this path instead of stdout")
    p.set_defaults(func=cmd_shortlist)

    caps_parser = sub.add_parser("caps", help="application cap commands")
    caps_sub = caps_parser.add_subparsers(dest="caps_command", required=True)
    p = caps_sub.add_parser("status", help="show current daily/company cap usage")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.add_argument(
        "--company", action="append", default=[], help="repeatable; show 7d usage for these"
    )
    p.set_defaults(func=cmd_caps_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (yaml.YAMLError, json.JSONDecodeError, TierConfigError, ConfigStructureError) as e:
        # Every command routes through here, so this one catch covers
        # malformed config/JSONL wherever it's read (boards.yaml,
        # blacklist.yaml, tier_overrides*.yaml, a `discover` JSONL file
        # fed to `shortlist`) -- a config typo, or a config whose root
        # shape is wrong (e.g. a `- x` YAML list where a mapping is
        # required), is a clean, exit-2 error, never a Python traceback.
        print(f"job-apply-kit: invalid config: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
