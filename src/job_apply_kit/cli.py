"""job-apply-kit CLI. Keyword scores, tiers, screener answers and caps stay
deterministic. Jev requirement extraction is a separately opted-in assist;
no model ever submits an application or asserts a candidate fact.
Keep README's CLI section in sync with these implemented commands.

Console script name: job-apply-kit (see pyproject.toml [project.scripts]).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

from . import demo
from .caps import (
    DEFAULT_DB_PATH,
    CapConfigError,
    CapExceededError,
    CapsLedger,
    load_caps_from_env,
    normalize_company,
)
from .decision_policy import requirement_mismatches, review_reasons
from .integrations import IntegrationError, load_integrations, setup, typesafe_key
from .jd_requirements import JevClient, Requirements
from .packet import render_packet
from .profile import ProfileError, load_profile, unconfirmed_facts
from .rank import RankedJob, rank_jobs
from .resume_tailor import DEFAULT_EVIDENCE, load_evidence
from .resume_update import update_resume
from .run_log import BestEffortLog, RunLog
from .self_heal import heal
from .shortlist import render_shortlist
from .sources.ashby import AshbyError
from .sources.ashby import fetch_jobs as fetch_ashby
from .sources.greenhouse import GreenhouseError, fetch_jobs
from .sources.lever import LeverError
from .sources.lever import fetch_jobs as fetch_lever
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


def _greenhouse_postings(token: str) -> list[dict]:
    return [
        {
            "title": j.title,
            "location": j.location,
            "url": j.absolute_url,
            "company": token,
            "company_name": j.company_name,
            "salary_amount": j.salary_amount,
            "salary_currency": j.salary_currency,
            "salary_period": j.salary_period,
            "description": j.description,
        }
        for j in fetch_jobs(token)
    ]


# boards.yaml section -> (per-entry key, fetch(slug) -> posting dicts, error to skip on).
# Lambdas so tests can monkeypatch the module-level fetch names.
SOURCES = {
    "greenhouse": ("board_token", lambda s: _greenhouse_postings(s), GreenhouseError),
    "lever": ("slug", lambda s: fetch_lever(s), LeverError),
    "ashby": ("slug", lambda s: fetch_ashby(s), AshbyError),
}


def _board_slugs(boards_raw: dict, name: str, key: str, path: Path) -> list[str]:
    entries = boards_raw.get(name) or []
    if not isinstance(entries, list):
        raise ConfigStructureError(f"{path}: '{name}' must be a list")
    for entry in entries:
        if not isinstance(entry, dict) or key not in entry:
            raise ConfigStructureError(f"{path}: each {name} entry must be a mapping with '{key}'")
    return [str(entry[key]) for entry in entries]


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

    overrides = _load_merged_tier_overrides()  # Validate overrides before fetching.
    blacklist = _blacklist(profile)
    if args.demo:
        print("DEMO: fictional jobs and mocked Jev; no network calls.")
        return _write_ranked(demo.postings(), profile, args, blacklist, overrides)

    boards_path = Path(args.boards)
    if not boards_path.exists():
        print(
            f"no boards config at {boards_path} (copy config/boards.example.yaml)", file=sys.stderr
        )
        return 1
    boards_raw = _require_mapping(yaml.safe_load(boards_path.read_text()), str(boards_path))
    boards = {
        name: _board_slugs(boards_raw, name, key, boards_path)
        for name, (key, _, _) in SOURCES.items()
    }
    if not any(boards.values()):
        print(f"no greenhouse/lever/ashby entries in {boards_path}", file=sys.stderr)
        return 1

    postings: list[dict] = []
    for name, slugs in boards.items():
        _, fetch, error = SOURCES[name]
        for slug in slugs:
            try:
                postings.extend(fetch(slug))
            except Exception as e:
                args.observer.record(
                    "discover", "failure", source=name, target=slug, code=type(e).__name__
                )
                if not isinstance(e, error):
                    raise
                print(f"skipping {name} board {slug!r}: {e}", file=sys.stderr)
            else:
                args.observer.record("discover", "success", source=name, target=slug)

    return _write_ranked(postings, profile, args, blacklist, overrides)


def _read_postings(path: str) -> list[dict]:
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if any(not isinstance(row, dict) or not isinstance(row.get("url"), str) for row in rows):
        raise ConfigStructureError("job JSONL rows must be mappings with a string URL")
    for row in rows:
        for key in ("title", "location", "company", "company_name", "description"):
            value = row.get(key)
            if value is not None and not isinstance(value, str):
                raise ConfigStructureError("job text fields must be strings or null")
            if key != "company_name" and key in row and value is None:
                row[key] = ""
        reasons = row.get("review_reasons")
        if reasons is not None and (
            not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons)
        ):
            raise ConfigStructureError("job review_reasons must be a list of strings")
    return rows


def _blacklist(profile) -> tuple[set[str], set[str]]:
    names, domains = _load_blacklisted_companies(DEFAULT_BLACKLIST_PATH)
    return names | {normalize_company(c) for c in profile.employer_blacklist.value}, domains


def _blocked(job: dict, blacklist: tuple[set[str], set[str]]) -> bool:
    return _is_blacklisted(job.get("company", ""), job.get("company_name"), job["url"], *blacklist)


def _write_ranked(postings: list[dict], profile, args, blacklist, overrides) -> int:
    before = len(postings)
    postings = [p for p in postings if not _blocked(p, blacklist)]
    if len(postings) < before:
        print(f"skipped {before - len(postings)} blacklisted posting(s)", file=sys.stderr)
    settings = load_integrations()
    evidence = load_evidence(Path(args.evidence))
    skills = profile.skills.value if profile.skills.state == "known" else []
    if evidence.skills.state == "known":
        skills = skills + evidence.skills.value
    transport = getattr(args, "jev_transport", None)
    if args.demo and transport is None:
        transport = demo.jev_transport()
    cache = Path("data/jev-demo.sqlite3" if args.demo else "data/jev.sqlite3")
    client = JevClient(settings, db=cache, transport=transport)
    by_url = {}
    for posting in postings:
        posting = dict(posting)
        if args.demo:
            posting["demo"] = True
        posting["requirements"] = client.get(posting, skills)
        posting["requirements_source"] = "jev" if posting["requirements"] is not None else "keyword"
        posting["requirements_note"] = client.last_status
        posting["review_reasons"] = requirement_mismatches(posting["requirements"], profile)
        posting["decision"] = "review_mismatch" if posting["review_reasons"] else "human_review"
        by_url[posting["url"]] = posting
    ranked = rank_jobs(list(by_url.values()), profile)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as stream:
        for job in ranked:
            row = {**by_url[job.url], **vars(job), "tier": detect_tier(job.url, overrides)}
            stream.write(json.dumps(row) + "\n")
    print(f"wrote {len(ranked)} ranked job(s) -> {out_path}")
    return 0


def cmd_packet(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    jobs = _read_postings(args.jobs)
    if args.url:
        jobs = [job for job in jobs if job["url"] == args.url]
    if len(jobs) != 1:
        raise IntegrationError("select exactly one job with --url")
    job = dict(jobs[0])
    args.observed_target = job["url"]
    settings = load_integrations()
    if not settings.jev_enabled or not typesafe_key():
        job["requirements"] = None
    if job.get("requirements") is not None:
        try:
            job["requirements"] = Requirements.model_validate(job["requirements"]).model_dump()
        except ValueError as exc:
            raise IntegrationError("invalid requirement snapshot in job JSONL") from exc
    if args.simplify and job.get("demo"):
        raise IntegrationError("demo packets cannot authorize a Simplify handoff")
    if _blocked(job, _blacklist(profile)):
        raise IntegrationError("packet refused: current blacklist blocks this job")
    if args.simplify:
        if not settings.simplify_enabled or not settings.simplify_risk_accepted:
            raise IntegrationError("Simplify handoff requires setup opt-in and risk acceptance")
        if review_reasons(job, profile):
            raise IntegrationError("verify requirements mismatch before a Simplify handoff")
    content = render_packet(
        job, profile, load_evidence(Path(args.evidence)), simplify=args.simplify
    )
    if args.simplify:
        with CapsLedger(args.db, config=load_caps_from_env()) as ledger:
            ledger.reserve(job.get("company") or urlparse(job["url"]).hostname or "unknown")
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"wrote packet for human review -> {path}")
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


def cmd_resume_update(args: argparse.Namespace) -> int:
    return update_resume(
        Path(args.source), Path(args.evidence), Path(args.profile), check=args.check
    )


def cmd_run_status(args: argparse.Namespace) -> int:
    if not 1 <= args.limit <= 200:
        raise IntegrationError("status limit must be between 1 and 200")
    print(json.dumps(args.observer.report(args.limit, args.target), indent=2))
    return 0


def cmd_self_heal(args: argparse.Namespace) -> int:
    return heal(args.observer, apply=args.apply)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-apply-kit")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("resume-update", help="validate/install user-edited resume evidence YAML")
    p.add_argument("source", help="existing YAML evidence draft, not a PDF or generated claims")
    p.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH))
    p.add_argument("--evidence", default=str(DEFAULT_EVIDENCE), help="private destination")
    p.add_argument("--check", action="store_true", help="validate only; do not write")
    p.set_defaults(func=cmd_resume_update)

    p = sub.add_parser("run-status", help="recent preparation/source failures; not submissions")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--target", help="filter by original board slug or application URL")
    p.set_defaults(func=cmd_run_status)

    p = sub.add_parser("self-heal", help="report failures; preview bounded catalogued repairs")
    p.add_argument("--apply", action="store_true", help="apply a validated catalogued repair")
    p.set_defaults(func=cmd_self_heal)

    p = sub.add_parser("interview-check", help="validate profile/candidate_profile.yaml")
    p.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH))
    p.set_defaults(func=cmd_interview_check)

    p = sub.add_parser("setup", help="post-interview opt-ins for Jev and Simplify")
    p.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH))
    p.add_argument("--jev", choices=["yes", "no"], default=None)
    p.add_argument("--simplify", choices=["yes", "no"], default=None)
    p.add_argument("--daily-budget", default=None, help="local Jev USD cap; zero blocks calls")
    p.add_argument("--monthly-budget", default=None, help="local Jev USD cap; zero blocks calls")
    p.add_argument("--accept-simplify-risk", action="store_true")
    p.set_defaults(func=setup)

    p = sub.add_parser("probe-boards", help="probe candidate Greenhouse board slugs")
    p.add_argument("slugs", nargs="+", help="candidate board_token values to try")
    p.add_argument("--keyword", default=None, help="only report jobs with this in the title")
    p.set_defaults(func=cmd_probe_boards)

    p = sub.add_parser(
        "discover", help="fetch configured Greenhouse/Lever/Ashby boards, rank, tier, write JSONL"
    )
    p.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH))
    p.add_argument("--boards", default=str(DEFAULT_BOARDS_PATH))
    p.add_argument("--out", default=str(DEFAULT_DISCOVER_OUT))
    p.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    p.add_argument("--demo", action="store_true", help="fictional offline jobs and mocked Jev")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("packet", help="prepare one Markdown packet; never operate a browser")
    p.add_argument("jobs")
    p.add_argument("--url", default=None, help="choose one job when JSONL contains several")
    p.add_argument("--profile", default=str(DEFAULT_PROFILE_PATH))
    p.add_argument("--evidence", default=str(DEFAULT_EVIDENCE))
    p.add_argument("--out", default="artifacts/packet.md")
    p.add_argument("--simplify", action="store_true", help="attended handoff; reserves a cap slot")
    p.add_argument("--db", default=str(DEFAULT_DB_PATH))
    p.set_defaults(func=cmd_packet)

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


def main(argv: list[str] | None = None, *, jev_transport: httpx.BaseTransport | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.jev_transport = jev_transport
    observer = None
    result, code = 2, "interrupted"
    observe = args.command != "run-status"
    args.observed_target = getattr(args, "url", None) or ""
    try:
        # Only commands that read the log need it; others observe best-effort.
        needs_log = args.command in {"run-status", "self-heal"}
        observer = args.observer = RunLog() if needs_log else BestEffortLog()
        if observe:
            observer.record(args.command, "started", target=args.observed_target)
        result = args.func(args)
        code = f"exit_{result}"
        return result
    except EOFError:
        code = "EOFError"
        print("setup requires answers; no settings changed", file=sys.stderr)
        return 2
    except (
        yaml.YAMLError,
        json.JSONDecodeError,
        TierConfigError,
        ConfigStructureError,
        IntegrationError,
        ProfileError,
        CapConfigError,
        CapExceededError,
        OSError,
        sqlite3.Error,
    ) as e:
        code = type(e).__name__
        # Every command routes through here, so this one catch covers
        # malformed config/JSONL wherever it's read (boards.yaml,
        # blacklist.yaml, tier_overrides*.yaml, a `discover` JSONL file
        # fed to `shortlist`) -- a config typo, or a config whose root
        # shape is wrong (e.g. a `- x` YAML list where a mapping is
        # required), is a clean, exit-2 error, never a Python traceback.
        print(f"job-apply-kit: invalid config: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        code = type(e).__name__
        raise
    finally:
        if observer is not None:
            try:
                if observe:
                    observer.record(
                        args.command,
                        "success" if result == 0 else "failure",
                        target=args.observed_target,
                        code=code,
                    )
            except (sqlite3.Error, OSError) as e:
                # A logging outage must not mask the original error or suggest
                # repeating a successful cap-reserving handoff.
                print(f"run observation unavailable: {type(e).__name__}", file=sys.stderr)
            finally:
                observer.close()


if __name__ == "__main__":
    sys.exit(main())
