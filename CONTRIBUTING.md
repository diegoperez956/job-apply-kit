# Contributing

## Setup

```bash
python -m venv .venv && .venv/bin/pip install -e .[dev]
./scripts/install_hooks.sh
```

## Before opening a PR

```bash
.venv/bin/ruff check .
.venv/bin/pytest
python3 scripts/pii_scan.py
```

All three must be clean. The `pii_scan.py` check is also wired as a
pre-commit hook after `install_hooks.sh`.

## Ground rules

- **No personal information in this repo, ever** -- no real names,
  emails, phone numbers, employer names, resumes, screenshots, API keys,
  or company blacklists tied to a person. Example/config files ship with
  placeholders only. If you're testing with your own profile, keep it in
  `profile/candidate_profile.yaml` (gitignored) and never `git add -f` it.
- **No new automation that submits an application.** This kit fills and
  ranks; a human always clicks submit for tier 2/3. Don't add code that
  bypasses that.
- **No CAPTCHA-solving or login-bypass code**, for any tier.
- **Deterministic first.** `answers.py`, `caps.py`, and `tier.py` are
  intentionally rule-based and LLM-free -- keep them that way. `llm.py`
  is opt-in and only for assistive/suggestive text (e.g. drafting a
  resume bullet), never for anything that decides what gets submitted or
  how a screener question is answered.
- **Ambiguous stays ambiguous.** If you're adding a new label to
  `answers.py`, an unmatched or unconfirmed case must resolve to `None`,
  not a best guess.

## Tests

Every module change should come with a test in `tests/`. Keep tests
fast and offline -- mock `httpx` calls (see `tests/test_greenhouse.py`),
don't hit real APIs.
