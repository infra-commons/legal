# Retirement executed: the divergent legal-review lineage in `infra-commons/security`

**Answers infra-commons/legal#22.** That issue was filed OPEN with a recommendation
(`reviews/2026-08-security-legal-lineage-divergence.md` supplied the measurement supporting it). The
operator decided to retire on 2026-08-15. This document records the execution of that decision — it
does not re-argue the recommendation.

**Justification is zero live callers plus duplication — not a suppression-bypass risk.** #22's
original framing ("a CRITICAL can be suppressed uncapped") described `legal-capture-findings-reusable.yml`,
deleted 2026-08-11 by `infra-commons/security#83`. The file retired here,
`legal-review-reusable.yml`, has zero "suppression" occurrences and never had a suppression
subsystem, so that framing never applied to it. That correction was already established before this
session started; it is restated here so it isn't re-introduced by anything that cites this issue
later.

## Live re-derivation, re-run today rather than trusted from the prior record

Per the task's constraint (`gh search code` has under-reported by org four times before in this
lane), the zero-caller count was re-derived live, not assumed from
`reviews/2026-08-security-legal-lineage-divergence.md`'s 2026-08-15 measurement, before anything was
deleted.

Enumerated every non-archived repo explicitly per org via `scripts/gh-app-token.sh <org>` (a fresh
App installation token per org; `bitcoinpolicynz` checked directly, no App install there):

| Org | Non-archived repos |
|---|---|
| `infra-commons` | 9 |
| `rolliq-com` | 12 |
| `cashbucket-com` | 8 |
| `klsjapan-com` | 6 |
| `chargingblindly-com` | 8 |
| `bitcoinpolicynz` | 3 |

**Total: 46**, matching the recorded figure. Fetched every `.github/workflows/*.yml` file fleet-wide
and grepped for `legal-review-reusable.yml` / `legal-capture-findings-reusable.yml`. Result: the only
`uses:` lines resolving to `infra-commons/security`'s copy were its own two delegate shims
(`klsjapan-com/security`, `chargingblindly-com/security`); nothing anywhere called either shim.
Confirms zero live callers, fleet-wide, direct or via shim — retirement proceeded on that basis. Had
a caller turned up, the correct action would have been to stop and hand back rather than continue;
that branch did not trigger.

## PRs opened

1. [`infra-commons/security#107`](https://github.com/infra-commons/security/pull/107) — deletes
   `.github/workflows/legal-review-reusable.yml` (405 lines) and its one-line row in `README.md`'s
   workflow table.
2. [`klsjapan-com/security#12`](https://github.com/klsjapan-com/security/pull/12) — deletes its
   delegate shim (`.github/workflows/legal-review-reusable.yml`, 12 lines). No `README.md` in that
   repo to update.
3. [`chargingblindly-com/security#5`](https://github.com/chargingblindly-com/security/pull/5) — same
   as #2, its own delegate shim.

All three mirror the shape of the already-completed, already-reviewed sibling retirement
(`infra-commons/security#83`, `klsjapan-com/security#11`, `chargingblindly-com/security#4`):
minimal diff, evidence-based body, no dependency on legal#23 (the unrelated tag-vs-SHA
delivery-contract decision). Opened by this session's automation identity; left for the operator to
review and merge, matching #83's own precedent (opened by the automation identity, merged by the
human operator).

## Scope correction found while executing

The prior assessment (`reviews/2026-08-security-legal-lineage-divergence.md`) recorded that its
worktree "may not write to `infra-commons/security`, `klsjapan-com/security`, or
`chargingblindly-com/security`," based on `GET /repos/{owner}/{repo}` reporting
`permissions.push: false` for the App-authenticated request. That field is not meaningful for an App
actor — it always reads false regardless of the installation's actual grant. The installation's real
grant, read from `GET /app/installations`, shows `contents: write`, `pull_requests: write`,
`workflows: write` on all five App-installed orgs (`infra-commons`, `rolliq-com`, `cashbucket-com`,
`klsjapan-com`, `chargingblindly-com`) with `repository_selection: all` — confirmed working in
practice by the three PRs above, none of which used a local clone. Worth knowing for any future
session that checks repo-permission reachability via that field before assuming it can't write
somewhere.
