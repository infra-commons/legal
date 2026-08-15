# Assessment: the divergent legal-reusable lineage in `infra-commons/security`

**Answers infra-commons/legal#22.** That issue is filed OPEN with a recommendation, explicitly not
an agreed plan — this document supplies the measurement it asked for, so the retire-vs-back-port
call can be made on evidence rather than the issue's own table, which turns out to be partly stale.
No decision has been executed by this document; it recommends.

## Summary and ranked recommendation

1. **Retire `infra-commons/security/.github/workflows/legal-review-reusable.yml` and its two
   delegate shims** (`klsjapan-com/security`, `chargingblindly-com/security`) — same shape as the
   already-completed retirement of the sibling capture-half file. Zero live callers, measured
   fleet-wide today; no release/verifier coverage to lose; no dependency on legal#23.
2. **Do nothing, as a fallback** — acceptable but strictly worse than #1. The file is already
   unreachable in practice (no caller resolves it), but it stays a stable, untagged, unverified
   `@main` address that anyone could wire up to in the future, same as #22 warned. Doing nothing
   doesn't cost anything today but leaves the loaded gun the issue described, now aimed at a smaller
   target than the issue thought.
3. **Back-port fixes into the security copy — not recommended.** There is nothing to back-port. See
   below: this file has no suppression subsystem, so #20/#21 don't apply to it. Porting one in would
   recreate a second maintained copy for a bug this copy structurally cannot have.

## What changed since #22 was filed

#22's table describes two divergent files. One of them is gone:

`infra-commons/security` PR **#83** ("chore(legal-capture): delete the orphaned duplicate reusable
workflow"), merged **2026-08-11**, deleted `.github/workflows/legal-capture-findings-reusable.yml`
outright — the half that actually carried the issue's named defects (`is_legal_suppressed` as the
unfixed #18 matcher, no `NEVER_SUPPRESSIBLE_SEVERITIES` cap from #20, no `drop_expired` from #21).
Companion PRs the same day, `klsjapan-com/security#11` and `chargingblindly-com/security#4`, deleted
its two delegate stubs. `infra-commons/meta#551` (closed) is the tracking issue; it verified zero
live callers before deletion using the same method this assessment repeats below, and its final
comment confirms all three deletions by direct 404 check.

Confirmed independently today (2026-08-15): `.github/workflows/legal-capture-findings-reusable.yml`
does not exist anywhere in `infra-commons/security`'s git tree at `main`.

**What #22 called "the review half" is the only piece still live**:
`.github/workflows/legal-review-reusable.yml`, unchanged since the same `eb10c258` (2026-07-10)
commit #22 cites.

## What's actually still live, and why #22's risk framing doesn't transfer to it

Read in full off `main` today. It is a self-contained ~470-line PR-time reviewer with a blocking
`gate` job (`has_critical` → hard-fails the gate). Compared to `infra-commons/legal`'s current
`legal-review-reusable.yml`:

| | `infra-commons/legal` (current) | `infra-commons/security` (this file) |
|---|---|---|
| Jurisdictions | configurable input (`NZ,AU`, `NZ,JP`, …) | hardcoded NZ/AU only, no input |
| Suppression subsystem | canonical + repo-local, `drop_expired`, prompt-hint advisory | **none — zero "suppression" occurrences** |
| CRITICAL handling | suppressions never override CRITICAL (enforced in the *capture* half) | no suppression code exists to override anything |

Grepping the file for "suppress" (case-insensitive) returns **zero hits** — matching #22's own
count. This is not a coincidence of omission; the file has no jurisdictions parameter, no canonical-
suppressions fetch, no `is_legal_suppressed`, nothing that could be missing a CRITICAL cap or an
expiry check, because it has no suppression matching code at all.

That matters for the recommendation: #22's headline risk — "a legal reviewer whose CRITICAL
findings can be suppressed with no cap and whose suppressions never expire" — describes the
*deleted* capture file's `is_legal_suppressed`/`NEVER_SUPPRESSIBLE_SEVERITIES`/`drop_expired` gap,
not this one. This file cannot leak a CRITICAL through an uncapped suppression, because it never
suppresses anything, ever. Its actual defect is the opposite direction: it predates the whole
suppression feature, so any of the ~30 accepted-false-positive categories now in
`infra-commons/legal`'s canonical suppressions file would re-surface as fresh CRITICAL/blocking
findings on every PR, for any caller still on this lineage. That's a noise/availability problem
(spurious merge blocks), not the under-suppression security problem #22's narrative leads with — a
correction worth making explicit for whoever next reads #22.

`infra-commons/security`'s own release/verifier machinery does not cover this file, confirming
#22's other claim still holds: no mention of "legal" in `release-composites.yml`, `pin-check.yml`,
or `workflow-lint.yml`. It's consumable only off `main`, with no tag and nothing checking it for
drift.

(Checked for interference: `infra-commons/security` PR #104, open against `tier-a.yml`/`tier-b.yml`
for an unrelated SAST-skip-gate fix, does not touch `legal-review-reusable.yml`. No conflict with
anything here.)

## Caller measurement — methodology and result

Per the task's constraint, this was measured live off each repo's default branch via
`scripts/gh-app-token.sh <org>` (a GitHub App installation token, minted fresh per org), never from
a local clone and never solely from `gh search code`.

**Coverage: all 6 reachable orgs, 46 non-archived repos.**

| Org | Non-archived repos | Access |
|---|---|---|
| `infra-commons` | 9 | App token |
| `rolliq-com` | 12 | App token |
| `cashbucket-com` | 8 | App token |
| `klsjapan-com` | 6 | App token |
| `chargingblindly-com` | 8 | App token |
| `bitcoinpolicynz` | 3 | No App install; checked directly via `gh api` (public org) |

For each repo, fetched the full `git/trees?recursive=true` listing, pulled every
`.github/workflows/*.yml`/`.yaml` file's raw content, and grepped for
`infra-commons/security` and, in `klsjapan-com`/`chargingblindly-com`, their own org's
`<org>/security` (to catch calls to the delegate shims). `bitcoinpolicynz`'s 3 repos carry exactly
one workflow between them (`secret-scan.yml`, twice) and no `legal-review` reference at all.

**Result: zero live callers of `infra-commons/security/.github/workflows/legal-review-reusable.yml`,
fleet-wide, direct or via shim.** The only three places the string
`infra-commons/security/.github/workflows/legal-review-reusable.yml@` appears as a `uses:` line
anywhere in the 46 repos are:

- The file's own header comment, documenting its caller pattern (`infra-commons/security@main`).
- `klsjapan-com/security/.github/workflows/legal-review-reusable.yml` — a thin delegate shim
  (`uses: infra-commons/security/.../legal-review-reusable.yml@main`, `secrets: inherit`).
- `chargingblindly-com/security/.github/workflows/legal-review-reusable.yml` — the same shim,
  identical shape.

Both shims are themselves dead ends: nothing in the other 5 repos of `klsjapan-com` or the other 7
repos of `chargingblindly-com` calls `<org>/security`'s `legal-review-reusable.yml`. (What those
repos *do* call from their org's `security` repo is `tier-a/b/c.yml` and
`adversarial-review-reusable.yml` — unrelated workflows, not legal review.)

Also checked whether either org's `security` repo's own `tier-a.yml`/`tier-b.yml`/`tier-c.yml`
internally composes `legal-review-reusable.yml` as a same-repo job (which would create a hidden
transitive caller no `uses:`-line grep across other repos would catch). Grepped all three tier
files in both `klsjapan-com/security` and `chargingblindly-com/security`, and in
`infra-commons/security` itself, for "legal": no hits anywhere except an unrelated repo-name mention
in a `chargingblindly-com/security` tier-c.yml comment. No transitive path exists.

This matches and extends `infra-commons/meta#551`'s 2026-08-10 measurement (which covered the now-
deleted capture file and its stubs, using the identical method) to the review half specifically.

## Cost and sequencing: retire vs. back-port

**Retire** — delete `infra-commons/security/.github/workflows/legal-review-reusable.yml` plus the
two delegate shims. Three small, single-file deletion PRs, identical in shape to
`infra-commons/security#83` (0 additions / ~470 deletions there) and its two companions (0
additions / ~12 deletions each). No caller anywhere needs a corresponding change, because none
exists. **No dependency on legal#23** (the delivery-contract decision, tag-vs-SHA pinning, still
open): retirement only removes a dead address inside `infra-commons/security` and two other repos —
it never touches an `infra-commons/legal` caller or a pin, so it is orthogonal to whichever way #23
resolves.

**Back-port #20/#21-equivalent fixes** — not costed as a real option, because there is no
suppression-cap or expiry bug in this file to fix (see above: no suppression code exists). The only
way to "fix" it in #22's sense would be to port the entire suppression subsystem (canonical fetch,
repo-local merge, `drop_expired`, jurisdictions) from `infra-commons/legal`'s current copy — i.e.
turn it back into a full duplicate. That recreates precisely the two-maintained-copies condition
`infra-commons/meta#560` and `#551` were opened to eliminate for the suppression file and the
capture workflow respectively, to solve a problem (CRITICAL suppression bypass) this file cannot
have. Ongoing cost: every future fix to `infra-commons/legal`'s review half would need manual
porting, forever, with no verifier watching for drift (confirmed above — none exists). Not
recommended under any near-term or long-term framing.

## Scope note

This assessment was produced from an `infra-commons/legal` worktree, which may not write to
`infra-commons/security`, `klsjapan-com/security`, or `chargingblindly-com/security`. No PR against
those repos has been opened or drafted here. If the operator accepts the recommendation, the next
step is three deletion PRs mirroring `infra-commons/security#83`'s shape, filed from a session with
write access to those three repos.

## Finding retained for the operator (not filed)

infra-commons/legal#22's table and narrative are now partly stale: the file it centers its risk
story on (`is_legal_suppressed`, line 423, "the original unfixed matcher, verbatim") was deleted
2026-08-11, four days before this assessment, and the risk it describes does not transfer to the
file that's actually still live. The issue's own recommendation ("retire rather than fix") is still
right for what remains, for different reasons than it originally gave. Worth the operator updating
or closing #22 with a pointer to this document — not done here, since no GitHub issue gets touched
by an assessment without being asked.
