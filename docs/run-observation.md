# Run observation and bounded self-heal

The kit prepares applications; it cannot observe what you do in your browser.
A successful packet or cap reservation is **not** a submitted application.
There is no browser access, login/CAPTCHA bypass, automated submit, retry loop,
or credential lookup in this feature.

## Inspect recent runs

Every CLI operation except `run-status` records a start and a terminal outcome
in the gitignored `data/runs.sqlite3` SQLite database. Discovery also records
success/failure for each configured public board, including skipped boards
when the overall discovery command succeeds. Unexpected parser exceptions
are recorded and re-raised, not hidden. An interrupted process may leave a
start without a terminal event; inspect that run before trying again.
Observation is best-effort for ordinary commands: if the DB is corrupt, locked
or unwritable they warn once on stderr and keep working. Only `run-status` and
`self-heal` need the log and exit 2 without it.

```bash
.venv/bin/job-apply-kit run-status
.venv/bin/job-apply-kit run-status --limit 50
.venv/bin/job-apply-kit run-status --target '<board-slug-or-job-url>'
```

The JSON report has `recent` events and `failures` grouped by source, target
and command. Each failure summary includes its count, last failure time, and
latest terminal outcome, so a later success does not look like an unresolved
failure. `--limit` (1–200, default 20) bounds the returned events and summaries;
failure counts cover the database's history, not just that event window.

Events contain UTC timestamps, run IDs, command/source names, outcomes, fixed
codes or exception class names, and SHA-256-derived target references. Raw
slugs, URLs, job text, profile facts, exception messages, HTTP responses and
credentials are **not** stored. A packet's final event correlates to its selected
URL; its start may have no target until selection completes. Use `--target`
with the original value to correlate it locally. Hashes are not anonymization:
keep this database private, and never publish captured terminal errors either.
There is no automatic retention policy; remove the private DB to clear history.
A missing DB shows an empty report. CLI usage/argument errors before execution
are not run events.

## Preview, then explicitly repair

```bash
.venv/bin/job-apply-kit self-heal
.venv/bin/job-apply-kit self-heal --apply
```

The default only reports observations and previews available repairs. `--apply`
uses a **closed deterministic repair catalog**, not an LLM or an arbitrary patch
executor. Currently its only repair is trimming accidental surrounding whitespace
in an existing `config/boards.yaml` board token/slug whose matching board has an
observed, still-unresolved failure. It preserves all other values and comments;
uncertain/blank slugs, block scalars, YAML anchors/aliases, symlinks, and unrelated
failures are reported without changes. It does not add boards or retry requests.

Before writing, the repaired text is re-parsed and must equal the original
with only slug whitespace trimmed, and it is loaded offline through the same
board loader `discover` uses: every repaired board must load with its trimmed
slug. Any mismatch, or more than **60 added + removed lines**, blocks the repair.
The config is then replaced atomically; nothing is fetched. Run `discover`
afterwards to confirm the board now resolves.

The allowlisted change surface is config YAML, source adapters under
`sources/*.py`, or tests, at most 60 changed lines. The current catalog is
**narrower**: only board-slug whitespace in `config/boards.yaml`; it does not
rewrite adapters/tests. All other failures require a reviewed manual fix.

No repair may lower caps/budgets, remove a blacklist, loosen tiering or Fact
checks, enable an integration, bypass site protections, or change human submit.
Passing validation alone is not permission to weaken these protections. Any future
catalog entry needs its own safety-preserving transformation and regression tests.
