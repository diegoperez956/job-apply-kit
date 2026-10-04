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
- **Pay ranges are uneven across sources.** Greenhouse and Lever only
  return salary data when the employer opted in to publish it, so
  `comp_ok` on most of their postings is the neutral "unknown" state.
  Ashby boards publish comp far more often. Only annual, monthly, and
  hourly figures are read; any other pay interval stays unknown.
- **Remote reachability is a hint, not a location-eligibility guarantee.**
  Ashby/Lever explicit remote metadata is retained alongside the named
  location. Ranking uses simple remote/substring matching, not geocoding
  or regional policy checks. Review country, state, and timezone limits
  yourself even when `location_ok` is true.
- **Run observation is local preparation history, not application outcomes.**
  The kit cannot tell whether a human submitted, received a reply, or hit a
  browser challenge. Self-heal uses a closed catalog (currently board-slug
  whitespace only), not general autonomous code repair. Unknown failures need
  manual review; see [the repair contract](run-observation.md).
- **No browser automation ships in this kit.** Tier 2/3 postings are
  read-only shortlist entries with a prep pack; nothing here drives a
  browser, fills a form, or clicks submit. That's left to whatever
  attended tooling you point at the shortlist yourself.
