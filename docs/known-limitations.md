# Known limitations

Honest gaps, not bugs to file:

- **The screener resolver (`answers.py`) is deterministic keyword
  matching, not NLU.** It classifies a label against a small fixed set
  of category keywords and a handful of negation/compound-question
  rules. Any phrasing it can't confidently place in exactly one category
  -- an unrecognized synonym, a compound question mixing a supported
  category with something it doesn't know, or a fact that isn't
  `state: known` -- resolves to `None`, on purpose. It never guesses.
  Use `resolve_reason()` to see why a given label came back blank, and
  expect to answer some fields by hand.
- **Greenhouse pay ranges are rarely exposed.** The public boards API
  only returns salary data when the employer opted in to publish it, so
  `comp_ok` on most postings is the neutral "unknown" state, not a real
  reachability signal.
- **No browser automation ships in this kit.** Tier 2/3 postings are
  read-only shortlist entries with a prep pack; nothing here drives a
  browser, fills a form, or clicks submit. That's left to whatever
  attended tooling you point at the shortlist yourself.
