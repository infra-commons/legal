# Delivery contract executed: `legal-review` moves on `legal-review/v1`

**Answers infra-commons/legal#23.** That issue was filed OPEN with a recommendation
(`reviews/2026-08-legal-delivery-contract.md` supplied the measurement and ranked options). The
operator decided on 2026-08-15 (comment on #23): **tag-pin `legal-review` only** via the moving tag
`legal-review/v1`; keep `legal-capture-findings`, `annual-review`, `quarterly-review` and
`legal-codebase-scan` SHA-pinned; build a pin-drift verifier regardless of which option won. This
document records the execution of that decision — it does not re-argue or extend it.

## What shipped

**Release mechanism** — `infra-commons/legal#35` (commit `9010a85`), built and merged before any
real tag move: `.github/workflows/release-legal-review.yml` plus three `.github/scripts/*.py`
scripts, authenticated as the `infra-commons-bot` App (Integration `4025350`) rather than
`GITHUB_TOKEN`. That identity is required because of this repo's two tag rulesets — `protect-
moving-tags` (id `19945087`) grants only the App a bypass on `refs/tags/*/v1` for `update` +
`deletion` + `non_fast_forward`, and `protect-immutable-tags` (id `19945085`) explicitly
**excludes** `refs/tags/*/v1` from its own zero-bypass `~ALL` scope (#25's first comment corrected
that issue's own body, which had misread the union of the two rulesets as blocking every actor).
No operator ruleset edit was ever required. The one real blocker was operational: the org secret
`INFRA_COMMONS_BOT_PRIVATE_KEY` was not yet granted to this repo. The release workflow's first real
run (`31915333695`) failed in 4 seconds at the token-mint step with exactly that error — the
documented failure mode for the ungranted state, not a defect. The operator granted the secret
2026-08-16; the re-run completed green.

**Tag advances, both independently re-verified by re-reading tags from the remote** (not trusting
the release step's own report):

| From | To | Version | Date | Delivered |
|---|---|---|---|---|
| `8f2fb0057fc7` | `b752b17e0263` | `legal-review/v1.1.0` | 2026-08-16 | #20/#21 — suppression-matcher fixes (closed #25) |
| `b752b17e0263` | `0156c6c80df3` | `legal-review/v1.2.0` | 2026-08-17 | #37 — `stop_reason == "max_tokens"` truncation guard |

Re-confirmed live in this session, `git ls-remote --tags origin`: `legal-review/v1` ==
`legal-review/v1.2.0` == `0156c6c80df3` == `refs/heads/main`'s current tip. The tag has never
drifted behind `main` since the mechanism went live — every push to `main` that passes `Tests` is
picked up by the next scheduled or dispatched release run, gated by the `legal-release`
environment's required human approval.

**Pin-drift verifier** — shipped as `infra-commons/meta#791` (`scripts/legal-pin-drift.py`,
`commands/legal-pin-drift.md`, exposed as `/legal-pin-drift`). This was the "regardless of which
option wins" half of the decision and lives outside this repo's boundary by design — the tool has
to read every caller org, not just this one.

## Caller migration, as last measured

Not this repo's work to merge (each org reviews its own), but recorded here for continuity since
the full picture otherwise only exists scattered across #23's ten comments:

- 2026-08-16: 12 caller PRs opened same-day across `rolliq-com` (9) and `cashbucket-com` (3),
  pinning to the tag's then-current commit. `klsjapan-com`'s 4 review-half call sites already
  tracked `legal-review/v1` before the decision.
- Residual, deliberately not converted to the tag: 4 `rolliq-com` repos
  (`clients-config`, `platform-iac`, `solution-recruitment-reference-check`, `solution-template`)
  hit an adversarial-review gate false positive on their tag-pin PRs (a finding true of the sibling
  `infra-commons/security` lineage's deletion-only ruleset, misapplied here). The operator ruled
  rewrite-to-SHA over suppression; those four were rewritten as SHA pins instead, then bumped
  SHA→SHA (`b752b17e` → `0156c6c8`) to close out #37's exposure without changing their posture.
  They remain SHA-pinned by deliberate choice, not oversight — converting them is a `rolliq-com`
  decision, not this repo's.
- `chargingblindly-com/legal` still pins 3 of its 4 legal-lineage call sites at `@main` directly
  (zero pin review of any kind, the same shape of exposure `security#59` found in Group A repos).
  Predates this decision, isn't fixed by it, and is a different org's repo — out of this session's
  charter, same as it was #23's original decision package's.

## What this document does not settle

#23's most recent comment (2026-08-17) flags, without proposing, that the four SHA-pinned
reusables now carry a standing cost the original decision didn't price: they receive a security
fix only via deliberate manual bump in every caller, with no drift-on-clock alerting between
`legal-pin-drift` runs. That is an open question, not a decision — extending tag-pinning, or
building an alert mechanism, would be a fresh call for the operator to make, not something this
document or the two doc-comment fixes accompanying it should pre-empt. `infra-commons/legal#23`
stays open to track it and the caller-migration residual above; this document does not close it.

## Scope note

This document only records prior action taken by other sessions and independently re-verifies the
tag/HEAD state live against the remote. From this session: two doc-comment corrections (the
`legal-review-reusable.yml` caller-pattern example, previously showing `@main`; `tests.yml`'s
header wording) and this file. No tag was moved, no pin was changed, no ruleset was touched, and no
caller PR was opened here.
