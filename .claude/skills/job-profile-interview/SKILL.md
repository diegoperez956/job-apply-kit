---
name: job-profile-interview
description: Grill-me style interview that builds profile/candidate_profile.yaml -- target roles, seniority, comp floors, location, work authorization, sponsorship, relocation, dealbreakers, self-ID, and a screener-answer bank. Use when the user wants to set up or update their job-search profile, run the job profile interview, or says "/job-profile-interview".
---

# Job Profile Interview

Build (or update) `profile/candidate_profile.yaml` by interviewing the
user one question at a time. This is a "grill-me" interview, not a form:
ask, recommend, listen, move on. Never batch multiple questions into one
message.

## Rules for every question

1. **One question at a time.** Wait for the answer before asking the
   next one.
2. **Recommend an answer.** Give your best default given what you know so
   far (e.g. "Most remote SWE roles at your stated seniority land
   $140k-$180k base -- want me to set your remote floor at $140k?"). The
   user can accept, adjust, or reject it.
3. **Record an honest state per fact**, not just a value:
   - `known` -- the user stated this directly and it's unambiguous.
   - `preference` -- a soft preference (dealbreakers, industries to
     avoid, self-ID) where "I don't know / doesn't matter" is a valid,
     confirmed answer.
   - `requires_confirmation` -- the user was unsure, skipped it, or gave
     an answer you had to interpret. **Never mark something `known` just
     because a question was asked** -- if they hedge, it's
     `requires_confirmation`.
4. **Don't invent facts.** If the user hasn't told you their work
   authorization status, leave it `requires_confirmation` with your best
   guess as `value` -- don't silently assume "US citizen."
5. **Load the schema first.** Read `src/job_apply_kit/profile.py` for the
   exact field names/types (note `authorizations` is a *list* of
   `{country, status, sponsorship_required}` -- work authorization is
   per-country, not one global value -- and `comp_floor_by_mode` values
   are `{amount, currency, period}`, not bare numbers) and
   `profile/candidate_profile.example.yaml` for a filled-in shape before
   writing YAML, so the file validates on the first try (`python -c
   "from job_apply_kit.profile import load_profile;
   load_profile('profile/candidate_profile.yaml')"`).

## Decision tree

Ask in this order -- later questions use earlier answers to sharpen the
recommendation (e.g. comp recommendations depend on seniority + location
mode; geography questions depend on location mode). **Every numbered item
below is its own turn** -- never ask two of these in one message, even
when they feel related (e.g. "willing to relocate?" and "where to?" are
two separate turns, not one).

1. **Target roles** -- "What job titles are you targeting?" Recommend
   2-4 closely related titles, not a scattershot list.
2. **Seniority** -- junior / mid / senior / staff / principal. Recommend
   based on the roles and any years-of-experience the user mentions.
2a. **Confirmed experience years** -- ask how many years of relevant
    experience the user can support. Record `experience_years`; unsure or
    declined means `null` / `requires_confirmation`, never a fixed default.
2b. **Confirmed skills** -- ask which technical skills the user can support
    from their own experience. Record `skills`; interests/target skills
    aren't confirmed skills. Optional Jev sends only confirmed skill names.
3. **Location mode** -- remote / hybrid / onsite, can be more than one.
   Recommend remote-first unless the user says otherwise.
4. **Geography** -- if hybrid/onsite is in scope, ask which
   cities/regions. If remote-only, confirm country/region (e.g.
   "US-remote").
5. **Comp floor, one question per location mode.** For each mode chosen
   in step 3, ask its floor (not a target) as its own separate turn --
   e.g. ask the remote floor, get an answer, *then* ask the hybrid floor.
   Recommend a number only if the user gives you enough signal (role +
   seniority + geography); otherwise mark `requires_confirmation` and ask
   them to research or state a rough number. Confirm currency (default
   USD) and period (default annual) if the user's answer implies
   otherwise (e.g. a non-US geography or an hourly-sounding number).
6. **Countries you're authorized to work in** -- "Which country(ies) are
   you authorized to work in?" Recommend the geography from step 4 as a
   default. This produces the list of countries step 7 loops over.
7. **Per-country status, one question per country from step 6.** For
   each country, ask its status (citizen / permanent resident / visa
   holder / needs sponsorship / other) as its own turn. This is
   high-stakes for screener answers downstream -- if there's any
   ambiguity, mark `requires_confirmation` rather than guess.
8. **Per-country sponsorship, one question per country from step 6.**
   For each country, ask separately whether sponsorship is required
   there -- don't fold this into step 7's question, and don't infer it
   from status even though it usually follows; confirm rather than infer
   if the user's status is complex (e.g. currently on a visa but
   eligible for a green card soon).
9. **Relocation** -- "Are you willing to relocate?" (yes/no only).
10. **Relocation cities** -- only if step 9 was yes: "Which
    cities/regions would you relocate for?" as its own separate turn.
11. **Start date** -- immediate / N weeks' notice / specific date.
12. **Non-compete** -- "Are you currently under a non-compete?"
    (yes/no only). Recommend "no" only if the user confirms no current
    agreement.
12a. **Security clearance** -- ask whether the user holds the clearance
     relevant to their target roles. Record `security_clearance`; unsure or
     declined stays `null` / `requires_confirmation`. Never infer a clearance.
13. **Non-compete restrictions** -- only if step 12 was yes: "What
    industry or geographic restrictions does it include?" as its own
    separate turn.
14. **Industries to avoid** -- optional list, `preference` state, empty
    list is a valid confirmed answer.
15. **Employer blacklist** -- optional list of company names to never
    surface, `preference` state.
16. **Dealbreakers** -- freeform list (e.g. "no on-call", "no return-to-office
    mandate"), `preference` state.
17. **Self-ID preferences, one question per field.** Ask gender, then
    race/ethnicity, then veteran status, then disability status as four
    separate turns. Default recommendation is `decline_to_answer` for
    each; only record something else if the user explicitly wants to.
18. **Links, one question per link.** Ask LinkedIn, then GitHub, then
    portfolio as three separate turns. URLs only, no other contact info.
19. **Screener-answer bank, one question per screener.** Ask about one
    common open-ended question at a time (e.g. first "Why this
    company/role?", get an answer, *then* "Tell us about a challenge you
    solved?") rather than asking for "1-3 answers" in one message. Stop
    after 1-3 questions once the user has given a couple of reusable
    answers, or sooner if they want to move on. Mark these
    `requires_confirmation` by default since a generic answer should be
    edited per posting; only mark `known` if the user gives you a
    genuinely reusable, final answer.

## Writing the file

After the last question, summarize every fact and its state back to the
user in one message and ask for a final confirmation before writing. Then
write `profile/candidate_profile.yaml` (gitignored -- this file holds the
user's real information and must never be committed). Validate it loads
cleanly with `load_profile()` before telling the user you're done. If
validation fails, fix the YAML and re-validate -- don't hand the user a
broken profile.

## Post-interview integration choices

After the confirmed profile validates, check **only presence**, never print
or ask for a token:

```bash
.venv/bin/python -c "from job_apply_kit.integrations import typesafe_key; print('present' if typesafe_key() else 'absent')"
```

Ask one question at a time:

1. "Wire in optional Jev / TypeSafe?" Recommend **no / keyword-only** unless
   the user wants structured JD requirements. Explain that only job text and
   confirmed skill names go to TypeSafe, never resume bullets or contact data.
2. If yes, guide them to https://typesafe.ai for a dedicated key and the
   private terminal prompt in `docs/integrations.md`. **Never accept or read
   the key in chat.** Ask the daily local USD cap as its own question, then
   the monthly cap. Zero blocks calls. Missing key stays keyword-only until
   they export `TYPESAFE_API_KEY`; a key alone never enables Jev.
3. "Do you use Simplify Copilot?" Recommend **no** unless they use/want its
   official extension. Explain `docs/simplify.md`: the human installs/logs in,
   the kit prepares a packet, the human checks every field and clicks submit.
4. If yes, ask separately whether they have read https://simplify.jobs/terms
   and accept the generic account/privacy risks. No acceptance: leave it off.

Record choices with `.venv/bin/job-apply-kit setup --jev yes|no --simplify
 yes|no`, passing `--daily-budget`/`--monthly-budget` only for user-chosen
amounts and `--accept-simplify-risk` only after explicit acceptance. Substitute
actual yes/no choices, don't run the literal alternatives. The CLI validates
the profile, checks key presence without exposing it, and writes only the
non-secret, gitignored `config/integrations.local.yaml`. Users may instead
run interactive `.venv/bin/job-apply-kit setup` themselves after the interview.
Do not invent resume bullets here; optional `profile/resume_evidence.yaml`
contains only user-provided, confirmed evidence (see its fictional example).

If a profile already exists, read it first and treat the interview as an
update: show current values as the recommended defaults so the user only
has to answer what changed.
