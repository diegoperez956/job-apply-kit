# job-apply-kit

Interview-driven job-search kit for Claude Code and the CLI. Build a
fact-checked profile, fetch public jobs, rank them, and prepare application
packets. **A human reviews every field and clicks submit.**

## Start here: the interview

In Claude Code, from this repo:

```
/job-profile-interview
```

The interview asks one question at a time, recommends an answer, and tags
facts `known`, `preference`, or `requires_confirmation`. It covers roles,
seniority, confirmed skills/experience, location and compensation,
work authorization, sponsorship, relocation, clearance, dealbreakers,
self-ID preferences, and reusable screener answers. You confirm the summary
before it writes the gitignored `profile/candidate_profile.yaml`.

**After the interview, run `job-apply-kit setup`.** It checks whether
`TYPESAFE_API_KEY` is present without showing it, then asks separately:

- Wire in **Jev / TypeSafe**? Default **no**: keyword-only. Yes guides you
  to obtain/export a key and choose local daily/monthly spending caps.
  A key alone never enables Jev. Missing key, zero/exhausted budget, or
  service failure leaves keyword matching available.
- Use **Simplify Copilot**? Default **no**. Yes explains installation,
  terms/account risks, and requires separate risk acceptance before a
  capped, human-operated handoff.

No Claude Code? Copy `profile/candidate_profile.example.yaml` to its real
name, fill it in yourself, run `interview-check`, then `setup`. Example
facts are fictional; don't use them in a real application.

## Quickstart: prove the pipeline runs without keys

```bash
git clone <this-repo> && cd job-apply-kit
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
./scripts/install_hooks.sh

# Run /job-profile-interview in Claude Code, or try the fictional profile:
cp profile/candidate_profile.example.yaml profile/candidate_profile.yaml
.venv/bin/job-apply-kit resume-update profile/resume_evidence.example.yaml
.venv/bin/job-apply-kit interview-check
.venv/bin/job-apply-kit setup             # answer no, then no for this demo
.venv/bin/job-apply-kit discover --demo
.venv/bin/job-apply-kit packet artifacts/ranked_jobs.jsonl
.venv/bin/job-apply-kit shortlist artifacts/ranked_jobs.jsonl --out artifacts/shortlist.md
.venv/bin/pytest -q
```

`--demo` uses one fictional job and a mocked TypeSafe endpoint; it makes
**no network requests**, even with a key present. Its cache is separate
from real jobs. Demo packets cannot reserve a Simplify handoff.

For real public boards, create the gitignored configuration:

```bash
cp config/boards.example.yaml config/boards.yaml
cp config/blacklist.example.yaml config/blacklist.yaml
# Replace example board slugs; edit the blacklist for yourself.
.venv/bin/job-apply-kit discover
.venv/bin/job-apply-kit packet artifacts/ranked_jobs.jsonl --url 'https://<actual-job-url>'
```

## Optional Jev: requirements, not invented candidate facts

Jev uses TypeSafe's **direct** `POST https://api.typesafe.ai/v1/systemone`
API (`jev-1.13.0`), not an AI gateway. Bounded choice questions extract
years, clearance, degree, work mode, sponsorship, seniority and
required/preferred skills. Only the job text and up to 25 confirmed skill
names are sent; no resume bullets, contact details, or screener answers.

Responses are validated per field; invalid answers stay unknown. Confirmed years/clearance mismatches are flagged for human
review, using **your** facts, never a fixed personal eligibility cutoff.
The keyword fit score remains deterministic. Extracted skills add relevance
signals when reordering your own confirmed resume evidence; they never
create skills or claims.

There is at most one request attempt per job URL in the local cache,
including failed/uncertain attempts. Re-running `discover` and packet preparation
reuse the result; packets never call TypeSafe. Requests reserve estimated
spend atomically before calling, against local UTC daily/monthly caps.
Failed attempts still count. These conservative local estimates are **not**
a provider-wide billing guarantee: verify pricing, use a dedicated key,
and set an account-side limit if available. See [integration notes](docs/integrations.md).

To try the opt-in path offline with a **fake** key:

```bash
TYPESAFE_API_KEY=demo-only .venv/bin/job-apply-kit setup --jev yes --simplify no \
  --daily-budget 0.01 --monthly-budget 0.05
TYPESAFE_API_KEY=demo-only .venv/bin/job-apply-kit discover --demo
TYPESAFE_API_KEY=demo-only .venv/bin/job-apply-kit packet artifacts/ranked_jobs.jsonl
# Disable again, or run interactive setup for real use:
.venv/bin/job-apply-kit setup --jev no --simplify no
```

For real use, export `TYPESAFE_API_KEY` through your secret manager or a
private terminal prompt, **not** as a literal command or CLI argument.
This kit reads only that process environment variable; it does not inspect
shared credential files, browser profiles, or other projects' accounts.
Never paste a key into the interview or commit a credentials file.

## Resume evidence and Simplify handoff

`profile/resume_evidence.yaml` is optional, personal and gitignored.
Follow its fictional example shape: confirmed skills and per-role bullet
blocks, each carrying a Fact state. A packet reorders only confirmed skills
and bullets **within their original role**. No addition, deletion, rewritten
claim, generated summary, LaTeX template, or PDF is involved. Unknown evidence
is omitted; without evidence you attach your own reviewed resume.

### Keep the resume source current

Start with an evidence draft (YAML, not a PDF):

```bash
cp profile/resume_evidence.example.yaml profile/resume-draft.local.yaml
# Edit this private draft with your current skills, roles and bullets.
# Keep uncertain claims requires_confirmation; mark known only after your review.
.venv/bin/job-apply-kit resume-update profile/resume-draft.local.yaml --check
.venv/bin/job-apply-kit resume-update profile/resume-draft.local.yaml
.venv/bin/job-apply-kit discover --demo
.venv/bin/job-apply-kit packet artifacts/ranked_jobs.jsonl
```

`resume-update` validates both the candidate profile and evidence with the existing
schemas, then atomically replaces `profile/resume_evidence.yaml`. Invalid/missing
input leaves the old source untouched. It does not extract a resume, invent text,
change Fact states, or overwrite the candidate profile/public example. Update
candidate facts separately through the interview or manual editing plus
`interview-check`. Drafts named `profile/*.local.yaml` are gitignored. If using
`--evidence` with another destination, keep it private/gitignored and pass that
same path to `discover` and `packet`. Regenerate old packets after each update;
only future runs read the new source. Confirmed evidence skills also feed
optional requirements matching, exactly as before.

Simplify Copilot is installed and operated by **you** in your own browser.
The kit prepares the packet and checklist; it does not launch a browser,
log in, fill a form, read cookies, or call a Simplify API. After interactive
`setup` and risk acceptance:

```bash
# Choose your own positive application limits; these are illustrative only.
export JOB_APPLY_DAILY_CAP=5 JOB_APPLY_PER_COMPANY_CAP=1 JOB_APPLY_TZ=UTC
.venv/bin/job-apply-kit packet artifacts/ranked_jobs.jsonl \
  --url 'https://<actual-job-url>' --simplify --out artifacts/simplify-packet.md
.venv/bin/job-apply-kit caps status
```

A Simplify handoff **reserves a cap slot before preparing the file**.
Repeated handoffs count again; cancelled/unused reservations aren't
refunded automatically. This is not evidence that an application was
submitted. Missing/invalid caps, a blacklist hit, or a known requirements
mismatch blocks the handoff. A mismatch flagged in the ranked JSONL still
blocks it later, even without `TYPESAFE_API_KEY` in that shell. Read [Simplify setup and account risks](docs/simplify.md).

## Observe runs and bounded self-heal

```bash
.venv/bin/job-apply-kit run-status
.venv/bin/job-apply-kit run-status --target '<board-slug-or-job-url>'
.venv/bin/job-apply-kit self-heal          # report/preview only
.venv/bin/job-apply-kit self-heal --apply  # explicit, test-gated known repair
```

Private structured observations live in `data/runs.sqlite3`: recent outcomes
and failures per source/application reference, including skipped boards.
No raw job/profile text, URLs, credentials, or exception messages are stored.
Packets/reservations are **not** submission confirmations; the kit cannot observe
browser outcomes. Self-heal currently repairs only observed board-token whitespace
in `config/boards.yaml`, at most 60 changed lines, with offline tests green before
and after (rollback on failure). Unknown problems are reported, never patched.
Caps, blacklists, Fact checks, login/CAPTCHA boundaries and human submit remain
unchanged. See [observation and repair contract](docs/run-observation.md).

## CLI

Use `.venv/bin/job-apply-kit` if your virtual environment isn't activated.

| Command | Output |
|---|---|
| `interview-check [--profile PATH]` | Validate the profile; list unconfirmed facts. |
| `resume-update SOURCE.yaml [--profile PATH] [--evidence PATH] [--check]` | Validate/install user-edited resume evidence; check-only leaves source unchanged. |
| `run-status [--limit N] [--target SLUG\|URL]` | Recent observations/failure summaries; not submission tracking. |
| `self-heal [--apply]` | Report/preview; explicit test-gated catalogued config repair only. |
| `setup [--jev yes\|no] [--simplify yes\|no]` | Post-interview opt-ins; local config only, no secrets. Interactive unless both choices supplied. |
| `probe-boards [--keyword K] SLUG...` | Probe public Greenhouse board slugs. |
| `discover [--demo] [--profile PATH] [--boards PATH] [--evidence PATH] [--out PATH]` | Fetch, blacklist-filter, keyword-rank, optionally extract requirements, tier, write JSONL. |
| `packet JOBS.jsonl [--url URL] [--evidence PATH] [--out PATH] [--simplify]` | One Markdown application packet; select a URL when several jobs are present. |
| `shortlist JOBS.jsonl [--profile PATH] [--out PATH]` | Ranked overview and suggestions explicitly marked `SUGGESTION`. |
| `caps status [--db PATH] [--company NAME]...` | Read-only reservation usage. |

Global `--run-log PATH` goes before the command and overrides the private run DB.
Default outputs are under gitignored `artifacts/`; local caches, run observations and cap
reservations are under `data/`. Opt-ins and spending caps live only in
`config/integrations.local.yaml`, never in the profile or public examples.

## Tiers and non-negotiables

| Tier | Meaning | Hosts |
|---|---|---|
| 1 | Read-only public API fetch, no login or browser | Greenhouse, Lever, Ashby |
| 2 | Attended extension-assisted application, human review/submit | Workday, iCIMS, SmartRecruiters |
| 3 | Curated manual application | Anything unrecognized |

Tier 1 is granted only to hosts with an implemented public fetch client;
unsupported overrides are clamped to tier 2. Ashby/Lever explicit remote
flags are preserved alongside their original location text. Regional
eligibility still needs human review.

- **No CAPTCHA/login bypass or scraping logged-in sites.** Stop on challenges,
  rate limits, logout, or uncertainty; never work around site protections.
- **No automatic submission, ever.** Jev is not an applier; Simplify is an
  attended, user-controlled tool. A human verifies uploads and every field.
- **Caps are enforced in code.** Application caps must be positive; Jev's
  separate spending caps may be zero to block calls.
- **Screener answers use confirmed profile facts only.** Jev output never
  becomes a candidate fact. Ambiguous labels, unconfirmed values, compound
  questions, unsafe negations and unknown countries resolve to `None`,
  never a guess. `resolve_reason()` explains why.
- **Nothing personal in git.** No real profiles, resumes, account data,
  keys, cookies, histories, job captures, logs, or browser artifacts.
  Keep the real filenames gitignored; examples are fictional.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) covers lint, offline tests and privacy
checks. See [design](docs/design.md) and [known limitations](docs/known-limitations.md).
MIT: [LICENSE](LICENSE).
