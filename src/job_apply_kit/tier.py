"""ATS tier routing.

Tier 1: unattended, deterministic, public API (e.g. Greenhouse boards API).
Tier 2: attended -- browser-extension-assisted, a human is present and
        clicks submit.
Tier 3: curated shortlist -- unknown/unsupported host, no automation,
        just a ranked entry with a prep pack.

Routing is by hostname, matched by suffix (so subdomains of a known ATS
host route correctly, e.g. "acme.myworkdayjobs.com" matches
"myworkdayjobs.com"). Unknown hosts default to tier 3 -- the safe
fallback is "ask a human to look at it", never "assume it's automatable".
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml

Tier = Literal[1, 2, 3]


class TierConfigError(ValueError):
    """A tier override value in a tier_overrides file isn't 1, 2, or 3."""


DEFAULT_TIER_BY_HOST: dict[str, Tier] = {
    # Tier 1: public boards API AND an implemented fetch client in
    # sources/ -- currently just Greenhouse (sources/greenhouse.py).
    "boards.greenhouse.io": 1,
    "job-boards.greenhouse.io": 1,
    # Known ATS with a public job-board API but no fetch client
    # implemented here yet -- tier 2 (attended) until sources/ gains one.
    "jobs.lever.co": 2,
    "jobs.ashbyhq.com": 2,
    "myworkdayjobs.com": 2,
    "icims.com": 2,
    "successfactors.com": 2,
    "taleo.net": 2,
    "jobs.smartrecruiters.com": 2,
    "greenhouse.io": 2,  # non-boards.* greenhouse pages (careers sites)
}


def _host_of(url_or_host: str) -> str:
    if "//" in url_or_host:
        return (urlparse(url_or_host).hostname or "").lower()
    return url_or_host.lower()


def _is_tier1_capable(host: str) -> bool:
    """True if `host` (or a parent of it) is one of the hosts DEFAULT_TIER_BY_HOST
    already grants tier 1 -- i.e. it has an implemented public-API fetch
    client in sources/. An override can't grant tier 1 to anything else."""
    capable = {h for h, t in DEFAULT_TIER_BY_HOST.items() if t == 1}
    return any(host == h or host.endswith("." + h) for h in capable)


def _validate_overrides(raw: dict, *, source: str) -> dict[str, Tier]:
    """Validate a host -> tier mapping: every value must be 1, 2, or 3,
    and a tier-1 grant to a host with no implemented public-API source is
    clamped to tier 2 with a warning -- tier 1 means "unattended, reads a
    public API we actually call", not "trust me". This is the ONLY place
    that decides whether a tier value is legit, used both for a loaded
    overrides file and for a mapping passed directly to detect_tier() --
    so there's no second, unvalidated path a bad tier-1 grant can sneak
    through."""
    if not isinstance(raw, dict):
        raise TierConfigError(
            f"{source}: expected a YAML mapping of host -> tier, got {type(raw).__name__}"
        )
    overrides: dict[str, Tier] = {}
    for host, tier in raw.items():
        host = str(host).lower()
        # Exact int only. bool is an int subclass (int(True) == 1) and
        # would otherwise sneak a truthy YAML `true` in as tier 1; float
        # would silently truncate (int(2.9) == 2); a numeral string
        # ("2") would silently coerce too. None of those are a
        # deliberate tier value, so reject the type outright rather than
        # coerce it.
        if isinstance(tier, bool) or not isinstance(tier, int):
            raise TierConfigError(
                f"{source}: tier for {host!r} must be 1, 2, or 3 (int), got {tier!r}"
            )
        tier_int = tier
        if tier_int not in (1, 2, 3):
            raise TierConfigError(f"{source}: tier for {host!r} must be 1, 2, or 3, got {tier_int}")
        if tier_int == 1 and not _is_tier1_capable(host):
            print(
                f"tier.py: {host!r} overridden to tier 1 but has no implemented public-API "
                "source (only Greenhouse boards do) -- clamping to tier 2",
                file=sys.stderr,
            )
            tier_int = 2
        overrides[host] = tier_int  # type: ignore[assignment]
    return overrides


def load_tier_overrides(path: str | Path) -> dict[str, Tier]:
    """Load and validate a host -> tier override mapping from a YAML
    file. Raises TierConfigError if any value isn't 1, 2, or 3."""
    p = Path(path)
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text())
    return _validate_overrides(raw if raw is not None else {}, source=str(path))


def detect_tier(url_or_host: str, overrides: dict[str, Tier] | None = None) -> Tier:
    """Return the tier for a job posting URL or bare hostname. Overrides
    (from config/tier_overrides.yaml, or any dict a caller passes
    directly) take priority over the built-in defaults and are validated
    the same way load_tier_overrides() validates a file -- a raw dict
    handed straight to this function isn't a trusted shortcut around that
    check, it goes through _validate_overrides() too, so a bogus or
    tier-1-for-an-unimplemented-host entry can't bypass validation just
    by skipping the file-loading path. An unrecognized host falls back to
    tier 3."""
    host = _host_of(url_or_host)
    if not host:
        return 3

    table = dict(DEFAULT_TIER_BY_HOST)
    if overrides:
        table.update(_validate_overrides(overrides, source="overrides"))

    # exact match first, then longest matching suffix
    if host in table:
        return table[host]
    best: tuple[int, Tier] | None = None
    for known_host, tier in table.items():
        if host.endswith("." + known_host) or host == known_host:
            if best is None or len(known_host) > best[0]:
                best = (len(known_host), tier)
    return best[1] if best else 3
