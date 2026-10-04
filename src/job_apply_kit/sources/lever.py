"""Lever postings public API client.

Tier-1 source, same rules as greenhouse.py: one public JSON endpoint, no
login, no CAPTCHA, no scraping.
Docs: https://github.com/lever/postings-api
"""

from __future__ import annotations

import httpx

from ._location import remote_location

POSTINGS_API = "https://api.lever.co/v0/postings/{slug}"

# Lever's salaryRange.interval values -> this kit's Period. Anything else
# (e.g. "one-time") stays unknown rather than being guessed at.
_PERIODS = {
    "per-year-salary": "annual",
    "per-month-salary": "monthly",
    "per-hour-wage": "hourly",
}


class LeverError(RuntimeError):
    """Raised on a non-2xx response or an unexpected payload shape."""


def _salary(item: dict) -> tuple[int | None, str, str]:
    """Range minimum from `salaryRange`, only when the posting publishes
    one. Missing/malformed -> (None, "USD", "annual"), i.e. unknown.

    ponytail: shape taken from Lever's postings-api docs; no live board
    checked while building this exposed salaryRange. A wrong guess stays
    dormant (comp shows unknown), never fabricates a number."""
    rng = item.get("salaryRange")
    if not isinstance(rng, dict):
        return None, "USD", "annual"
    low = rng.get("min")
    period = _PERIODS.get(str(rng.get("interval")))
    if not isinstance(low, (int, float)) or isinstance(low, bool) or period is None:
        return None, "USD", "annual"
    return int(low), str(rng.get("currency") or "USD").upper(), period


def fetch_jobs(slug: str, *, timeout: float = 10.0) -> list[dict]:
    """Fetch all open postings for a Lever company slug (the path segment
    in jobs.lever.co/<slug>). Returns posting dicts in the shape
    `cli discover` ranks; raises LeverError if the slug doesn't exist or
    the API errors."""
    url = POSTINGS_API.format(slug=slug)
    try:
        resp = httpx.get(url, params={"mode": "json"}, timeout=timeout)
    except httpx.HTTPError as e:
        raise LeverError(f"request to {url} failed: {e}") from e

    if resp.status_code == 404:
        raise LeverError(f"no Lever postings found for slug {slug!r}")
    if resp.status_code != 200:
        raise LeverError(f"{url} returned HTTP {resp.status_code}")

    try:
        payload = resp.json()
    except ValueError as e:
        raise LeverError(f"unexpected response shape from {url}: {e}") from e
    if not isinstance(payload, list):
        raise LeverError(f"unexpected response shape from {url}: not a list")

    jobs = []
    for item in payload:
        if not isinstance(item, dict) or not item.get("hostedUrl"):
            continue
        categories = item.get("categories") if isinstance(item.get("categories"), dict) else {}
        amount, currency, period = _salary(item)
        jobs.append(
            {
                "title": item.get("text") or "",
                "location": remote_location(
                    categories.get("location") or "", workplace_type=item.get("workplaceType")
                ),
                "url": item["hostedUrl"],
                "company": slug,
                "company_name": None,
                "salary_amount": amount,
                "salary_currency": currency,
                "salary_period": period,
            }
        )
    return jobs
