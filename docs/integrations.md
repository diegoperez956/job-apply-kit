# Optional integrations

## Jev / TypeSafe

`setup` runs only after a valid profile exists. It reports key presence,
asks for opt-in, and records non-secret settings in the gitignored
`config/integrations.local.yaml`. Default is off. A zero spending cap is
closed, not unlimited. Choose caps yourself; there is no shared account
lookup or imported credential/spending file.

For a real key, use a secret manager or, in a private Bash terminal:

```bash
read -rs -p 'TypeSafe API key: ' TYPESAFE_API_KEY; echo
export TYPESAFE_API_KEY
.venv/bin/job-apply-kit setup
```

Never print the variable, paste it into a chat, add it to a profile, or
put its literal value in shell history. A key is never written by this kit.
The process environment is the only credential source.

### Extraction contract

- Direct System One endpoint: `https://api.typesafe.ai/v1/systemone`.
  Pinned model: `jev-1.13.0`; review provider documentation before changing it.
- Only bounded `choice` questions, with explicit enums and per-option
  probabilities. Six scalar questions plus at most 25 deduplicated,
  confirmed skill names. No unverified list/score primitives.
- Job HTML is unescaped and stripped. The 4,000-character window prioritizes
  requirements headings. The full cleaned text also supplies the first
  numeric years match; both heuristics need human verification.
- Request body at most 32 KiB, response at most 128 KiB, ten-second timeout,
  no redirects or automatic retries. Errors never include raw bodies or keys.
- Each answer is checked separately: real enum choice, numeric confidence
  in [0,1], probabilities covering exactly the enum and summing to about 1.
  Invalid fields remain unknown without discarding valid fields.
- The only candidate information sent is a confirmed skill-name catalog.
  No work bullets, identity/contact fields, resume uploads or screener answers.

### Cache and budget contract

`data/jev.sqlite3` stores sanitized requirement results and conservative
local cost reservations. The credential is never persisted. A transaction
claims each job URL before transport, so concurrent/repeated callers cannot
spend twice. Failed, timed-out or interrupted attempts remain claimed and
charged locally, rather than risking a duplicate bill.

Reservation uses serialized request bytes plus an overhead allowance at the
model's recorded input-token rate. Actual usage, when greater, increases the
local accounting. Pricing changes, hidden provider overhead, other clients,
and the provider's real invoice are outside this local guard. Verify pricing
and use provider account limits where available. Daily/monthly boundaries
are UTC; zero/exhausted caps prevent a request before transport.

No key, disabled integration, missing JD, cap hit, unavailable cache, provider
error or invalid response falls back to keyword matching. Cached results are
used only while opted in and a key is present. Cache identity is the job URL,
not the description/profile version: changing a JD or skill catalog does not
trigger a second request. Treat cached data as a review aid, not fresh proof.
Do not delete the cache to evade caps; that would erase local accounting.
Demo jobs use a separate cache and a mocked transport.

### Consumers

Keyword fit scores, tiers and screener answers remain deterministic.
`decision_policy.py` flags years/clearance mismatches only against confirmed
user facts; unknown is not a negative signal. A requirements mismatch blocks
a Simplify handoff until reviewed; an ordinary packet can still be prepared
for inspection. Model output never becomes a candidate fact.

`resume_tailor.py` uses the job text plus extracted required/preferred skills
to reorder existing, confirmed evidence. Additive relevance is not permission
to add a skill, employer, date, number, summary or claim. Markdown packets
contain the original strings, grouped under their original role. Rendering
escapes HTML; no PDF/LaTeX template or generated prose is shipped.
