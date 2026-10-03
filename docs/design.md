# Design notes

## Why a `state` on every fact

The failure mode this kit is built to avoid is a bot confidently telling
an employer something the candidate never actually said -- "yes, I'm
authorized to work here" inferred from silence. Wrapping every fact in
`{value, state}` (`known` / `preference` / `requires_confirmation`) makes
"I don't actually know this yet" a first-class, machine-checkable state
instead of an implicit default. `answers.py` treats
`requires_confirmation` the same as "no fact at all": it returns `None`
rather than the guessed value. That's the whole safety property in one
sentence.

## Why three tiers instead of one

Different ATS platforms offer wildly different levels of "safe to
automate": a public JSON API (Greenhouse boards) can be read
unattended forever with zero risk of touching a login wall or a
CAPTCHA. A platform like Workday has no such API here, needs a real
browser session, and should have a human watching every field before
anything is submitted. Collapsing that into one automation tier either
overreaches on the API-only case (adds browser risk where none is
needed) or underreaches on the attended case (skips the review step
that catches a wrong field). `tier.py` keeps the routing explicit and
host-based so the tier for a given posting is always inspectable, not
inferred at run time.

## Why caps reject zero

A cap is meant to bound *how many* applications happen. Encoding "apply
to nothing" as `daily_cap: 0` conflates "bounded to zero" with
"misconfigured" -- and a bug that silently turns any other cap into zero
would look identical to an intentional pause. `caps.py` raises
`CapConfigError` on zero (and negative) values; if you want to pause,
don't invoke the applier.

## Why `answers.py` is keyword matching, not an LLM

Screener-answer resolution is the one place a wrong answer has real
consequences (a false "yes, authorized to work" is worse than a blank
field). Keyword classification is auditable in one read of
`_CATEGORY_KEYWORDS` -- you can see exactly which phrases map to which
profile fact, and exactly what happens when nothing matches (`None`).
An LLM classifier would be more flexible and strictly harder to reason
about for a component whose failure mode is "asserted something false."
`llm.py` exists for the opposite kind of task -- suggestive text with no
correctness requirement, like a first-draft resume bullet a human is
always going to edit.

## What's deliberately out of scope

- Browser automation code. Tier 2 is "browser-extension-assisted" by
  design -- the extension and the human are outside this repo's scope;
  this kit only decides *what* tier a posting is and prepares the data
  (profile facts, prep pack) a tier-2 flow would consume.
- An LLM client/SDK dependency. `llm.py` shells out to the `claude` CLI
  if present; there's no vendor SDK in `pyproject.toml`.
- ATS sources without a public, no-login job-board API (Workday, iCIMS,
  LinkedIn, ...). Greenhouse, Lever, and Ashby are each one small module
  in `sources/` plus a tier-1 entry in `tier.py`; another public API
  slots in the same way.
