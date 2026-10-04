"""Public source fetch -> ranking contract for explicit remote metadata."""

from __future__ import annotations

import httpx
import pytest

from job_apply_kit.profile import Fact
from job_apply_kit.rank import rank_jobs
from job_apply_kit.sources import ashby, lever


def _fetch(monkeypatch, source, location, metadata):
    if source is ashby:
        payload = {
            "jobs": [
                {
                    "title": "Backend Engineer",
                    "location": location,
                    "jobUrl": "https://jobs.ashbyhq.com/example-co/1",
                    "compensation": {
                        "summaryComponents": [
                            {
                                "compensationType": "Salary",
                                "interval": "1 YEAR",
                                "currencyCode": "USD",
                                "minValue": 180000,
                            }
                        ]
                    },
                    **metadata,
                }
            ]
        }
    else:
        payload = [
            {
                "text": "Backend Engineer",
                "categories": {"location": location},
                "hostedUrl": "https://jobs.lever.co/example-co/1",
                "salaryRange": {
                    "min": 180000,
                    "currency": "USD",
                    "interval": "per-year-salary",
                },
                **metadata,
            }
        ]
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **kwargs: httpx.Response(200, json=payload),
    )
    return source.fetch_jobs("example-co")


@pytest.mark.parametrize(
    "source,metadata",
    [
        (ashby, {"isRemote": True}),
        (ashby, {"workplaceType": "Remote"}),
        (lever, {"workplaceType": "remote"}),
        (lever, {"workplaceType": " REMOTE "}),
    ],
)
@pytest.mark.parametrize("location", ["New York", "Remote - United States", ""])
def test_explicit_remote_metadata_reaches_ranking(
    monkeypatch, profile_factory, source, metadata, location
):
    postings = _fetch(monkeypatch, source, location, metadata)
    profile = profile_factory(
        location_mode=Fact(value=["remote"], state="preference"),
        geography=Fact(value=["Austin, TX"], state="preference"),
    )
    ranked = rank_jobs(postings, profile)
    assert ranked[0].location_ok is True
    assert ranked[0].comp_ok is True  # Remote compensation floor is now selected.
    assert location in ranked[0].location  # Keep the employer's named geography for review.
    assert ranked[0].location.lower().count("remote") == 1

    # Explicit remote does not make a remote-only job reachable for someone
    # who only accepts onsite roles in a different city.
    onsite_profile = profile_factory(
        location_mode=Fact(value=["onsite"], state="preference"),
        geography=Fact(value=["Austin, TX"], state="preference"),
    )
    assert rank_jobs(postings, onsite_profile)[0].location_ok is False


@pytest.mark.parametrize(
    "source,metadata",
    [
        (ashby, {}),
        (ashby, {"isRemote": False}),
        (ashby, {"isRemote": "true"}),
        (ashby, {"isRemote": 1}),
        (ashby, {"workplaceType": "Hybrid"}),
        (ashby, {"workplaceType": "OnSite"}),
        (lever, {}),
        (lever, {"workplaceType": "hybrid"}),
        (lever, {"workplaceType": "on-site"}),
        (lever, {"workplaceType": None}),
        (lever, {"workplaceType": ["remote"]}),
    ],
)
def test_missing_nonremote_or_malformed_metadata_is_not_guessed(
    monkeypatch, profile_factory, source, metadata
):
    postings = _fetch(monkeypatch, source, "New York", metadata)
    profile = profile_factory(
        location_mode=Fact(value=["remote"], state="preference"),
        geography=Fact(value=["Austin, TX"], state="preference"),
    )
    ranked = rank_jobs(postings, profile)
    assert ranked[0].location == "New York"
    assert ranked[0].location_ok is False
    assert ranked[0].comp_ok is None
