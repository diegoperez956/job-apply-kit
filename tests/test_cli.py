from __future__ import annotations

import json

import pytest
import yaml

from job_apply_kit import cli
from job_apply_kit.caps import normalize_company
from job_apply_kit.sources.greenhouse import GreenhouseJob


def _write_profile(tmp_path, profile) -> None:
    (tmp_path / "profile").mkdir(exist_ok=True)
    (tmp_path / "profile" / "candidate_profile.yaml").write_text(
        yaml.dump(profile.model_dump(mode="json"))
    )


def _write_boards(tmp_path, tokens: list[str]) -> None:
    (tmp_path / "config").mkdir(exist_ok=True)
    body = "greenhouse:\n" + "".join(f"  - board_token: {t!r}\n" for t in tokens)
    (tmp_path / "config" / "boards.yaml").write_text(body)


# Q5 repro: a blacklisted company is absent from `discover` output.


def test_discover_filters_blacklisted_company(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    _write_boards(tmp_path, ["Acme", "Blocked Co"])
    (tmp_path / "config" / "blacklist.yaml").write_text('companies:\n  - "Blocked Co"\n')

    def fake_fetch_jobs(token, *, timeout=10.0):
        return [
            GreenhouseJob(
                id=1,
                title="Backend Engineer",
                location="Remote",
                absolute_url=f"https://boards.greenhouse.io/{token}/jobs/1",
                board_token=token,
            )
        ]

    monkeypatch.setattr(cli, "fetch_jobs", fake_fetch_jobs)

    assert cli.main(["discover"]) == 0

    rows = [
        json.loads(line)
        for line in (tmp_path / "artifacts" / "ranked_jobs.jsonl").read_text().splitlines()
        if line.strip()
    ]
    companies = {row["company"] for row in rows}
    assert "Acme" in companies
    assert "Blocked Co" not in companies
    # wiring sanity: comp_ok is present and labeled (no salary data from
    # Greenhouse here, so it's the "unknown" neutral value).
    assert all(row["comp_ok"] is None for row in rows)


def test_discover_no_blacklist_file_is_a_noop(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    _write_boards(tmp_path, ["Acme"])

    monkeypatch.setattr(
        cli,
        "fetch_jobs",
        lambda token, **kw: [
            GreenhouseJob(
                id=1,
                title="Backend Engineer",
                location="Remote",
                absolute_url="https://boards.greenhouse.io/acme/jobs/1",
                board_token=token,
            )
        ],
    )

    assert cli.main(["discover"]) == 0
    rows = [
        json.loads(line)
        for line in (tmp_path / "artifacts" / "ranked_jobs.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(rows) == 1


# Q6: malformed YAML/JSON anywhere in cli.py -> clean message, exit 2, no traceback.


def test_discover_malformed_boards_yaml_exits_2(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "boards.yaml").write_text("greenhouse: [unterminated: [\n")

    assert cli.main(["discover"]) == 2


def test_discover_malformed_blacklist_yaml_exits_2(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    _write_boards(tmp_path, ["Acme"])
    (tmp_path / "config" / "blacklist.yaml").write_text("companies: [unterminated: [\n")
    monkeypatch.setattr(cli, "fetch_jobs", lambda token, **kw: [])

    assert cli.main(["discover"]) == 2


def test_discover_malformed_tier_overrides_exits_2(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    _write_boards(tmp_path, ["Acme"])
    (tmp_path / "config" / "tier_overrides.yaml").write_text("some.host.example: 9\n")

    assert cli.main(["discover"]) == 2


def test_shortlist_malformed_jsonl_exits_2(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    jobs_file = tmp_path / "jobs.jsonl"
    jobs_file.write_text("{not valid json}\n")

    assert cli.main(["shortlist", str(jobs_file)]) == 2


# Q4 repro: `- x` style YAML (a list at the root, not a mapping) is a
# clean exit-2 error, not a traceback, for every config discover reads.


def test_discover_boards_yaml_root_list_exits_2(tmp_path, monkeypatch, profile, capsys):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "boards.yaml").write_text("- x\n")

    assert cli.main(["discover"]) == 2
    assert "invalid config" in capsys.readouterr().err


def test_discover_boards_yaml_bad_entry_exits_2(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "boards.yaml").write_text("greenhouse:\n  - 1\n  - 2\n")

    assert cli.main(["discover"]) == 2


def test_discover_blacklist_yaml_root_list_exits_2(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    _write_boards(tmp_path, ["Acme"])
    (tmp_path / "config" / "blacklist.yaml").write_text("- x\n")
    monkeypatch.setattr(cli, "fetch_jobs", lambda token, **kw: [])

    assert cli.main(["discover"]) == 2


def test_discover_tier_overrides_yaml_root_list_exits_2(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    _write_boards(tmp_path, ["Acme"])
    (tmp_path / "config" / "tier_overrides.yaml").write_text("- x\n")
    monkeypatch.setattr(cli, "fetch_jobs", lambda token, **kw: [])

    assert cli.main(["discover"]) == 2


# Q4 repro: blacklist matching normalizes company display name, board
# token, and domain -- "blocked co" == "blocked-co" -- and also honors
# profile.employer_blacklist.


def test_discover_blacklist_matches_normalized_company_display_name(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    _write_boards(tmp_path, ["acme-token"])
    # blacklist entry uses punctuation/spacing that differs from the
    # board's company_name ("Blocked-Co" vs "Blocked Co") but normalizes
    # to the same key.
    (tmp_path / "config" / "blacklist.yaml").write_text('companies:\n  - "Blocked-Co"\n')

    from job_apply_kit.sources.greenhouse import GreenhouseJob

    def fake_fetch_jobs(token, *, timeout=10.0):
        return [
            GreenhouseJob(
                id=1,
                title="Backend Engineer",
                location="Remote",
                absolute_url="https://boards.greenhouse.io/acme-token/jobs/1",
                board_token=token,
                company_name="Blocked Co",
            )
        ]

    monkeypatch.setattr(cli, "fetch_jobs", fake_fetch_jobs)

    assert cli.main(["discover"]) == 0
    rows = [
        json.loads(line)
        for line in (tmp_path / "artifacts" / "ranked_jobs.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert rows == []


# Domain blacklist matching is by host-suffix boundary, never a bare
# substring: "notacme.com" must never match a blacklisted "acme.com".


def test_is_blacklisted_domain_matches_by_host_suffix_boundary():
    domains = {"acme.com"}
    assert cli._is_blacklisted("x", None, "https://acme.com/jobs/1", set(), domains) is True
    assert cli._is_blacklisted("x", None, "https://boards.acme.com/jobs/1", set(), domains) is True
    assert cli._is_blacklisted("x", None, "https://notacme.com/jobs/1", set(), domains) is False


# A dotted blacklist entry ("Exampleco.io") is matched BOTH as a domain and
# as a normalized display name, so it blocks a posting either by URL host
# or by the ATS's exposed company display name.


def test_load_blacklisted_companies_dotted_entry_is_both_domain_and_name(tmp_path):
    p = tmp_path / "blacklist.yaml"
    p.write_text('companies:\n  - "Exampleco.io"\n')
    names, domains = cli._load_blacklisted_companies(p)
    assert "exampleco.io" in domains
    assert normalize_company("Exampleco.io") in names


def test_is_blacklisted_dotted_entry_blocks_by_display_name(tmp_path):
    p = tmp_path / "blacklist.yaml"
    p.write_text('companies:\n  - "Exampleco.io"\n')
    names, domains = cli._load_blacklisted_companies(p)
    # matched via display name, even though the posting URL host differs
    # entirely from the blacklisted domain.
    is_blocked = cli._is_blacklisted(
        "mon-token", "Exampleco.io", "https://boards.greenhouse.io/mon-token/jobs/1", names, domains
    )
    assert is_blocked is True


# Structural validation: a config file's parsed root must be explicitly
# checked, never `safe_load(...) or {}` (which silently turns a falsey-
# but-wrong-type root like `[]` into `{}` and hides the mistake).


def test_discover_boards_yaml_empty_file_exits_2(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "boards.yaml").write_text("")

    assert cli.main(["discover"]) == 2


def test_discover_boards_yaml_empty_list_exits_2(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "boards.yaml").write_text("[]\n")

    assert cli.main(["discover"]) == 2


def test_discover_blacklist_yaml_empty_list_exits_2(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    _write_boards(tmp_path, ["Acme"])
    (tmp_path / "config" / "blacklist.yaml").write_text("[]\n")
    monkeypatch.setattr(cli, "fetch_jobs", lambda token, **kw: [])

    assert cli.main(["discover"]) == 2


def test_load_blacklisted_companies_empty_file_is_a_noop(tmp_path):
    # an empty (all-comments/blank) personal blacklist.yaml is not an
    # error -- it just means nothing is blacklisted, same as a missing
    # file. Only a wrong-*type* root (a list) is a structural error.
    p = tmp_path / "blacklist.yaml"
    p.write_text("")
    assert cli._load_blacklisted_companies(p) == (set(), set())


def test_load_tier_overrides_empty_list_root_raises(tmp_path):
    from job_apply_kit.tier import TierConfigError, load_tier_overrides

    p = tmp_path / "tier_overrides.yaml"
    p.write_text("[]\n")
    with pytest.raises(TierConfigError):
        load_tier_overrides(p)


def test_load_tier_overrides_empty_file_is_a_noop(tmp_path):
    # an empty personal tier_overrides.local.yaml is not an error --
    # same convenience as the blacklist file.
    from job_apply_kit.tier import load_tier_overrides

    p = tmp_path / "tier_overrides.yaml"
    p.write_text("")
    assert load_tier_overrides(p) == {}


def test_discover_honors_profile_employer_blacklist(tmp_path, monkeypatch, profile_factory):
    from job_apply_kit.profile import Fact
    from job_apply_kit.sources.greenhouse import GreenhouseJob

    p = profile_factory(employer_blacklist=Fact(value=["Acme"], state="known"))
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, p)
    _write_boards(tmp_path, ["acme"])

    def fake_fetch_jobs(token, *, timeout=10.0):
        return [
            GreenhouseJob(
                id=1,
                title="Backend Engineer",
                location="Remote",
                absolute_url=f"https://boards.greenhouse.io/{token}/jobs/1",
                board_token=token,
            )
        ]

    monkeypatch.setattr(cli, "fetch_jobs", fake_fetch_jobs)

    assert cli.main(["discover"]) == 0
    rows = [
        json.loads(line)
        for line in (tmp_path / "artifacts" / "ranked_jobs.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert rows == []


def test_discover_merges_lever_and_ashby_boards_as_tier_1(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "boards.yaml").write_text(
        "lever:\n  - slug: lever-co\nashby:\n  - slug: ashby-co\n  - slug: gone-co\n"
    )

    def posting(company, url):
        return {"title": "Backend Engineer", "location": "Remote", "url": url, "company": company}

    def fake_ashby(slug):
        if slug == "gone-co":
            raise cli.AshbyError("no Ashby job board found")
        return [posting(slug, f"https://jobs.ashbyhq.com/{slug}/1")]

    monkeypatch.setattr(
        cli, "fetch_lever", lambda slug: [posting(slug, f"https://jobs.lever.co/{slug}/1")]
    )
    monkeypatch.setattr(cli, "fetch_ashby", fake_ashby)

    assert cli.main(["discover"]) == 0

    rows = [
        json.loads(line)
        for line in (tmp_path / "artifacts" / "ranked_jobs.jsonl").read_text().splitlines()
    ]
    assert {row["company"]: row["tier"] for row in rows} == {"lever-co": 1, "ashby-co": 1}


def test_discover_lever_bad_entry_exits_2(tmp_path, monkeypatch, profile):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, profile)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "boards.yaml").write_text("lever:\n  - board_token: wrong-key\n")

    assert cli.main(["discover"]) == 2
