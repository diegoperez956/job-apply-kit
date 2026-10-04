"""Ashby job-board public API client.

Tier-1 source, same rules as greenhouse.py: one public JSON endpoint, no
login, no CAPTCHA, no scraping.
Docs: https://developers.ashbyhq.com/docs/public-job-posting-api
"""

from __future__ import annotations

import httpx

from ._location import remote_location

JOB_BOARD_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

# Ashby compensation intervals -> this kit's Period. Anything else
# (weekly, quarterly, ...) stays unknown rather than being guessed at.
_PERIODS = {"1 YEAR": "annual", "1 MONTH": "monthly", "1 HOUR": "hourly"}


class AshbyError(RuntimeError):
    """Raised on a non-2xx response or an unexpected payload shape."""


def _salary(item: dict) -> tuple[int | None, str, str]:
    """Minimum of the first Salary component in `compensation.summaryComponents`,
    only when the board publishes it (`includeCompensation=true`).
    Missing/malformed -> (None, "USD", "annual"), i.e. unknown."""
    comp = item.get("compensation")
    components = comp.get("summaryComponents") if isinstance(comp, dict) else None
    if not isinstance(components, list):
        return None, "USD", "annual"
    for c in components:
        if not isinstance(c, dict) or str(c.get("compensationType")).casefold() != "salary":
            continue
        low = c.get("minValue")
        period = _PERIODS.get(str(c.get("interval")).upper())
        if not isinstance(low, (int, float)) or isinstance(low, bool) or period is None:
            return None, "USD", "annual"
        return int(low), str(c.get("currencyCode") or "USD").upper(), period
    return None, "USD", "annual"


def fetch_jobs(slug: str, *, timeout: float = 10.0) -> list[dict]:
    """Fetch all listed jobs for an Ashby job-board name (the path segment
    in jobs.ashbyhq.com/<slug>). Returns posting dicts in the shape
    `cli discover` ranks; raises AshbyError if the board doesn't exist or
    the API errors."""
    url = JOB_BOARD_API.format(slug=slug)
    try:
        resp = httpx.get(url, params={"includeCompensation": "true"}, timeout=timeout)
    except httpx.HTTPError as e:
        raise AshbyError(f"request to {url} failed: {e}") from e

    if resp.status_code == 404:
        raise AshbyError(f"no Ashby job board found for {slug!r}")
    if resp.status_code != 200:
        raise AshbyError(f"{url} returned HTTP {resp.status_code}")

    try:
        raw_jobs = resp.json()["jobs"]
    except (ValueError, KeyError, TypeError) as e:
        raise AshbyError(f"unexpected response shape from {url}: {e}") from e
    if not isinstance(raw_jobs, list):
        raise AshbyError(f"unexpected response shape from {url}: jobs is not a list")

    jobs = []
    for item in raw_jobs:
        if not isinstance(item, dict) or not item.get("jobUrl") or item.get("isListed") is False:
            continue
        amount, currency, period = _salary(item)
        jobs.append(
            {
                "title": item.get("title") or "",
                "location": remote_location(
                    item.get("location") or "",
                    is_remote=item.get("isRemote"),
                    workplace_type=item.get("workplaceType"),
                ),
                "url": item["jobUrl"],
                "company": slug,
                "company_name": None,
                "salary_amount": amount,
                "salary_currency": currency,
                "salary_period": period,
            }
        )
    return jobs
