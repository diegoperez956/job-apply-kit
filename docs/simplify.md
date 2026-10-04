# Simplify Copilot: attended handoff

Simplify Copilot lives at https://simplify.jobs/copilot. Install its official
extension yourself in your own browser and sign in manually. Read the actual
terms at https://simplify.jobs/terms; this document is generic account-risk
reasoning, not a claim about what those terms allow.

## Division of labor

- **The kit:** prepares a Markdown packet of confirmed evidence and screener
  answers, checks your current blacklist, and reserves a local cap slot.
- **Simplify's extension:** fills supported fields using the profile you
  maintain in Simplify. That profile is separate; the kit does not synchronize
  it or assume its answers are correct.
- **You:** open the job page, handle any ordinary authentication yourself,
  inspect every field/upload and self-ID answer, then click submit.

The kit never launches a browser, uses a browser profile, reads cookies,
accepts credentials, calls a Simplify API, or clicks the extension's submit
control. No scheduled/unattended lane exists here.

## Setup

1. Finish the profile interview; run `.venv/bin/job-apply-kit setup`.
2. Choose Simplify only if you intend to use it. Read the linked terms and
   accept account risks explicitly; declining keeps this handoff disabled.
3. Install the official extension and configure its profile yourself.
4. Set positive `JOB_APPLY_DAILY_CAP` and `JOB_APPLY_PER_COMPANY_CAP` values
   in your process environment. `JOB_APPLY_TZ` defaults to UTC.
5. Run `packet JOBS.jsonl --url URL --simplify`. Bring its reviewed content
   to the form yourself. Nothing in that command opens or submits anything.

Missing opt-in/risk acceptance, missing or invalid caps, an exhausted cap,
a current blacklist hit, or a known years/clearance mismatch refuses the
handoff. A demo packet cannot authorize a handoff. Ordinary `packet` output
is still available for manual review without the extension.

Each successful handoff conservatively reserves a slot *before* producing
the file. Recreating it counts again. An abandoned handoff is not refunded,
and a reservation is not a submitted-application record. These controls only
bound this kit's handoffs, not applications you make outside it.

## Account and privacy risks

Any account-based extension may be rate-limited or blocked. Frequent/burst
use, prohibited automation, repeated submissions or an extension defect can
put an account at risk. Do not disguise automation, rotate accounts, bypass
limits or assume human presence makes every action permitted.

An extension can see form contents and sensitive candidate information.
Review its permissions/privacy policy, avoid sharing the browser profile,
and keep packets, opt-ins and cap records out of git. The kit's private local
files aren't public examples and should not be attached to issue reports.

Stop on a CAPTCHA/challenge, logout, 401/403/429, account warning or uncertain
field. Investigate manually; never retry around a protection. You can stop or
decline submit at any time. Only you can decide whether the service's terms
and your circumstances permit using its extension on a particular site.
