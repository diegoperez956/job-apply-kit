# job-apply-kit

A Claude Code (and general CLI) kit for job hunting: a grill-me interview
builds a structured, fact-checked job-search profile, then deterministic
code uses that profile to fetch, rank, and shortlist jobs -- with prep
packs grounded only in what you actually told it.

It is not a mass-application bot. It will not click "submit" for you, log
into a site on your behalf, or solve a CAPTCHA. See [Non-negotiables](#non-negotiables).

## Start here: the interview

Everything downstream reads one file, `profile/candidate_profile.yaml`,
and the interview is how you build it. In Claude Code, from this repo:

```
/job-profile-interview
```

It's a grill-me interview
(`.claude/skills/job-profile-interview/SKILL.md`): one question at a
time, a recommended answer offered each time, your response recorded
with an honest state -- `known`, `preference`, or
`requires_confirmation`. It walks target roles, seniority, comp floors
by location mode (with currency/period), remote/hybrid/onsite,
geography, per-country work authorization and sponsorship, relocation,
start date, non-compete, industries to avoid, employer blacklist,
dealbreakers, self-ID preferences, and a screener-answer bank, then
writes the profile against the schema in `src/job_apply_kit/profile.py`.

Then check it (after the [quickstart](#5-minute-quickstart) install):

```bash
job-apply-kit interview-check   # validates, lists anything still requires_confirmation
```

No Claude Code? Copy `profile/candidate_profile.example.yaml` (fake
data, full shape) to `profile/candidate_profile.yaml` and fill it in by
hand. The real file is gitignored -- keep it that way.

## What it does

1. **Interview** -- see [Start here](#start-here-the-interview). Every
   answer is tagged `known`, `preference`, or `requires_confirmation` so
   downstream code never treats a guess as a fact.
2. **Source** -- pulls open jobs from public, no-login ATS APIs:
   Greenhouse, Lever, and Ashby job boards.
3. **Rank** -- drops any posting from a blacklisted company
   (`config/blacklist.yaml`, personal and gitignored), then scores what's
   left for title/keyword fit against your target roles and checks
   location/comp reachability against your profile. Comp reachability
   respects currency and pay period (hourly/monthly figures are
   annualized before comparing); a posting with no salary, no confirmed
   comp floor for that mode, or a currency this kit can't convert is left
   labeled unknown, never silently treated as reachable or not.
4. **Route by tier** -- classifies each posting's host into tier 1, 2, or
   3 (see below) so you know exactly how much automation is appropriate
   for that specific application.
5. **Shortlist** -- renders a ranked markdown shortlist with a prep pack
   per job: a fit rationale grounded in your profile, suggested resume
   bullets clearly marked `SUGGESTION` (this kit doesn't know your actual
   work history), and pre-drafted screener answers pulled deterministically
   from your profile facts.

## 5-minute quickstart

```bash
git clone <this-repo> && cd job-apply-kit
python -m venv .venv && .venv/bin/pip install -e .[dev]
./scripts/install_hooks.sh          # pre-commit PII scan, once

# 1. In Claude Code: /job-profile-interview   (see Start here above)

# Copy every *.example.yaml in config/ to its real (gitignored) name --
# these hold personal data (board list, blacklist) and must never be
# committed. config/tier_overrides.local.yaml has no .example seed file;
# create it yourself only if you need personal tier overrides.
cp config/boards.example.yaml config/boards.yaml
cp config/blacklist.example.yaml config/blacklist.yaml
cp .env.example .env               # set your daily / per-company caps

job-apply-kit interview-check
job-apply-kit probe-boards --keyword "engineer" acme acme-inc
job-apply-kit discover
job-apply-kit shortlist artifacts/ranked_jobs.jsonl
.venv/bin/pytest
```

Nothing here applies to a job on your behalf. The output of a full run is
a markdown shortlist and prep packs for you to review and act on.

## CLI

Installing the package (`pip install -e .`) puts a `job-apply-kit`
console script on PATH. This is the only automation surface in the kit --
nothing here submits an application. Commands:

| Command | What it does |
|---|---|
| `job-apply-kit interview-check [--profile PATH]` | Loads and validates `profile/candidate_profile.yaml` against the schema; lists any fact still `requires_confirmation`. |
| `job-apply-kit probe-boards [--keyword K] SLUG...` | Checks whether each Greenhouse board-token slug exists and reports matching open jobs. |
| `job-apply-kit discover [--profile PATH] [--boards PATH] [--out PATH]` | Fetches every board in `config/boards.yaml` (`greenhouse`, `lever`, `ashby` sections) via their public job-board APIs, drops any posting whose company matches `config/blacklist.yaml` (if present), ranks and tiers what's left, writes one JSON row per job to a JSONL file (default `artifacts/ranked_jobs.jsonl`). |
| `job-apply-kit shortlist JOBS.jsonl [--profile PATH] [--out PATH]` | Renders the markdown shortlist + prep packs from a `discover` JSONL file. |
| `job-apply-kit caps status [--db PATH] [--company NAME]...` | Prints current daily and per-company-7d usage from the durable caps ledger (`data/caps.sqlite3` by default). |

`caps status` is read-only. There is no `apply`/`reserve` command in this
CLI -- `caps.py`'s `CapsLedger.reserve()` exists for other code (e.g. a
tier-2 browser-extension flow, out of this repo's scope) to call when it
actually records a submitted application.

## The three-tier model

Every job posting's ATS host gets classified (`src/job_apply_kit/tier.py`,
overridable in `config/tier_overrides.yaml` -- shared/committed -- and
`config/tier_overrides.local.yaml` -- personal, gitignored, merged on
top) into exactly one tier:

| Tier | Name | What happens | Example hosts |
|---|---|---|---|
| 1 | Unattended, deterministic | Fetched and read via a public API this kit actually implements (`sources/greenhouse.py`, `lever.py`, `ashby.py`), no login, no CAPTCHA, no browser | `boards.greenhouse.io`, `job-boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashbyhq.com` |
| 2 | Attended, browser-extension-assisted | A browser session fills what it can from your profile; **a human reviews every field and clicks submit** | `*.myworkdayjobs.com`, `*.icims.com`, `jobs.smartrecruiters.com` |
| 3 | Curated shortlist | No automation at all -- ranked entry + prep pack, you apply by hand | anything unrecognized |

Tier 1 is only ever granted to a host with an implemented fetch client in
`sources/` -- Greenhouse, Lever, and Ashby. This is enforced
in `detect_tier()` itself, not just in the file loader -- any override
mapping, whether it came from `config/tier_overrides*.yaml` or was passed
in directly, is validated the same way: a value that isn't 1, 2, or 3 is
rejected, and a tier-1 grant to anything else is clamped to tier 2 with a
warning (`tier.py`).

There is no tier that submits an application without a human present. Tier
1 only ever *reads* public data; it never posts a form on your behalf.

## Non-negotiables

- **No CAPTCHA or login bypass, ever.** If a site requires solving a
  CAPTCHA or authenticating as you to see a posting, this kit doesn't
  touch it.
- **No scraping logged-in sites.** Tier 1 sources are public APIs only.
- **Caps are enforced in code, not configuration alone.** `caps.py`
  rejects a cap of zero as a config error -- "off" is not a valid cap
  value, don't run the tool if you don't want it to count anything.
- **Every answer to a screener question comes only from profile facts.**
  `answers.py` resolves a small set of well-known fields (work
  authorization and sponsorship for a given target country,
  relocation, salary-by-location-mode, start date, links)
  deterministically from the profile. It resolves to `None` (never a
  guess) when: the label is ambiguous or matches more than one category
  (including a compound "X or Y?"/"X and Y?" label that mixes a
  supported category with something it doesn't recognize), the backing
  fact isn't `state: known` (a `preference` is an opinion to confirm by
  hand, not an assertable fact -- see `Fact` in `profile.py`), a
  work-authorization/sponsorship question has no matching country on
  file, or a negated question ("unwilling"/"not willing"/"without"/
  "never"/"no longer") lands on a category it can't safely invert.
  "Eligible to work without sponsorship?" is Yes only when the profile's
  authorization status for that country is actually authorized AND
  `sponsorship_required` is false -- a `not_authorized` status always
  reads No, regardless of the sponsorship flag. `resolve_reason()`
  explains any `None`.
- **A human clicks submit for tier 2 and tier 3.** Attended-tier
  automation fills fields; it does not submit.

## Project layout

```
.claude/skills/job-profile-interview/SKILL.md   the interview
src/job_apply_kit/cli.py                        `job-apply-kit` console script (see CLI above)
src/job_apply_kit/profile.py                    schema + loader + validation
src/job_apply_kit/answers.py                    deterministic label -> fact resolver
src/job_apply_kit/sources/greenhouse.py         tier-1 public API fetch
src/job_apply_kit/sources/lever.py              tier-1 public API fetch
src/job_apply_kit/sources/ashby.py              tier-1 public API fetch (with published comp)
src/job_apply_kit/sources/probe_boards.py       find a company's Greenhouse slug
src/job_apply_kit/rank.py                       fit scoring + reachability
src/job_apply_kit/tier.py                       ATS host -> tier routing
src/job_apply_kit/caps.py                       durable daily / per-company-7d cap ledger
src/job_apply_kit/shortlist.py                  markdown shortlist + prep packs
src/job_apply_kit/llm.py                        optional `claude -p` shim, no-op otherwise
config/                                         example boards/blacklist/tier config
scripts/pii_scan.py                             pre-commit PII scan
tests/                                          pytest suite
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Design notes in
[docs/design.md](docs/design.md). Honest gaps in
[docs/known-limitations.md](docs/known-limitations.md).

## License

MIT, see [LICENSE](LICENSE).
