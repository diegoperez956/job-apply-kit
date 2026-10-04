"""Greenhouse job-boards public API client.

This is the reference tier-1 source: no login, no CAPTCHA, no scraping --
just the public JSON API every Greenhouse-hosted careers page is built on.
Docs: https://developers.greenhouse.io/job-board.html
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

BOARDS_API = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"


@dataclass
class GreenhouseJob:
    id: int
    title: str
    location: str
    absolute_url: str
    board_token: str
    # Company display name, when the board JSON exposes one
    # (`company_name`, observed on live boards) -- else None, fall back
    # to the board_token for display.
    company_name: str | None = None
    # Salary/compensation passthrough. Only ever set from data the
    # posting itself exposes (`pay_input_ranges`, present when a board
    # publishes pay-transparency data and the API is queried with
    # `?content=true`) -- never invented. None/defaults mean "unknown",
    # not "no salary" -- see README's comp-reachability note.
    salary_amount: int | None = None
    salary_currency: str = "USD"
    salary_period: str = "annual"
    description: str = ""


class GreenhouseError(RuntimeError):
    """Raised on a non-2xx response or an unexpected payload shape."""


def _salary_from_pay_input_ranges(ranges: object) -> tuple[int | None, str, str]:
    """Best-effort extraction of one comparable salary figure from a
    job's `pay_input_ranges`. Uses the range MINIMUM (not the midpoint
    or max) so a posting is never counted comp-reachable on an
    optimistic number this kit made up. Missing/malformed input ->
    (None, "USD", "annual"), i.e. unknown, never a guessed figure.

    ponytail: this field wasn't observed on any live board checked while
    building this (pay_input_ranges may only appear for boards that
    opted into pay-transparency publishing) -- the {min_cents,
    currency_type, pay_period} shape assumed here is a best guess.
    Adjust the key names if a real payload turns out to differ; the
    None-on-anything-unexpected fallback means a wrong guess just stays
    dormant (comp shows as unknown) rather than fabricating a number.
    """
    if not isinstance(ranges, list) or not ranges:
        return None, "USD", "annual"
    first = ranges[0]
    if not isinstance(first, dict):
        return None, "USD", "annual"
    min_cents = first.get("min_cents")
    if not isinstance(min_cents, (int, float)) or isinstance(min_cents, bool):
        return None, "USD", "annual"
    currency = str(first.get("currency_type") or "USD").upper()
    period = str(first.get("pay_period") or "annual")
    return int(min_cents) // 100, currency, period


def fetch_jobs(board_token: str, *, timeout: float = 10.0) -> list[GreenhouseJob]:
    """Fetch all open jobs for a Greenhouse board token (the slug in
    boards.greenhouse.io/<board_token>). Returns an empty list if the
    board exists but has no jobs; raises GreenhouseError if the board
    token doesn't exist or the API errors.

    Queries with `content=true` so a board's pay-transparency data
    (`pay_input_ranges`), when present, comes through -- see
    _salary_from_pay_input_ranges().
    """
    url = BOARDS_API.format(board_token=board_token)
    try:
        resp = httpx.get(url, params={"content": "true"}, timeout=timeout)
    except httpx.HTTPError as e:
        raise GreenhouseError(f"request to {url} failed: {e}") from e

    if resp.status_code == 404:
        raise GreenhouseError(f"no Greenhouse board found for token {board_token!r}")
    if resp.status_code != 200:
        raise GreenhouseError(f"{url} returned HTTP {resp.status_code}")

    try:
        payload = resp.json()
        raw_jobs = payload["jobs"]
    except (ValueError, KeyError, TypeError) as e:
        raise GreenhouseError(f"unexpected response shape from {url}: {e}") from e

    jobs = []
    for j in raw_jobs:
        location = (j.get("location") or {}).get("name", "")
        salary_amount, salary_currency, salary_period = _salary_from_pay_input_ranges(
            j.get("pay_input_ranges")
        )
        jobs.append(
            GreenhouseJob(
                id=j["id"],
                title=j["title"],
                location=location,
                absolute_url=j["absolute_url"],
                board_token=board_token,
                company_name=j.get("company_name"),
                salary_amount=salary_amount,
                salary_currency=salary_currency,
                salary_period=salary_period,
                description=j.get("content") if isinstance(j.get("content"), str) else "",
            )
        )
    return jobs
