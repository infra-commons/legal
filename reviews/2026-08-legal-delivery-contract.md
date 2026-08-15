# Decision package: the `infra-commons/legal` delivery contract — moving tag or SHA pins

*Answers infra-commons/legal#23. That issue gates #24 ("should the four untagged reusables be
released at all?") and #25 (the `legal-review/v1` tag move) — both are explicitly blocked on this
one. #23 already carried a recommendation but zero comments and no operator decision; this
document re-derives its numbers live rather than trusting them, and packages the three issues as
one decision. It recommends. It does not decide, and nothing below moved a tag or changed a pin.*

## Summary and ranked recommendation

1. **Tag-pin `legal-review` only; keep the other four SHA-pinned; build a pin-drift verifier
   regardless.** This is #23's original recommendation and the fresh census below does not
   overturn it — if anything it strengthens the case, because SHA-pin freshness is already visibly
   uneven in practice (§"What changed"), not just a theoretical risk. Requires building a release
   mechanism that runs as the `infra-commons-bot` App (§Cost), a caller PR in each of 12 repos to
   reach the tag, and the sequencing in §Safety before the tag itself ever moves.
2. **Formalize SHA-pinning fleet-wide (status quo) plus a pin-drift verifier.** Cheaper to build —
   no release mechanism needed — but relies on caller discipline that today is already inconsistent
   within single repos (§"What changed"). Acceptable, strictly worse than #1 on the security-relevant
   half.
3. **Not recommended: tag-pin all five reusables.** Extends the required-human-review-on-every-merge
   burden and the no-per-caller-pin-review blast radius to four low-frequency reusables for no
   corresponding benefit; #24's original reasoning holds under the fresh numbers too.

## Fresh measurement — methodology and result

Measured today (2026-08-15) by GitHub App installation token, never a static PAT and never a local
clone: `scripts/gh-app-token.sh <org>` (App id `4025350`) for `infra-commons`, `rolliq-com`,
`cashbucket-com`, `klsjapan-com`, `chargingblindly-com`; plain unauthenticated `gh api` for
`bitcoinpolicynz` (the App is not installed there — 3 public repos, still zero legal-workflow
callers of any kind, confirmed fresh). The static per-org PATs (`gh-rolliq`, `gh-cashbucket`,
`gh-klsjapan`) were not used — the first two were pulled from their orgs today and now 404, the
third is separately 404-blind. `gh search code` was not used at all — enumerated every non-archived
repo per org explicitly instead, since it has under-reported by org on at least four prior
occasions in this lane.

Enumeration: all 46 non-archived repos across the 6 reachable orgs (`infra-commons` 9,
`rolliq-com` 12, `cashbucket-com` 8, `klsjapan-com` 6, `chargingblindly-com` 8, `bitcoinpolicynz` 3).
For each, fetched every file under `.github/workflows/` at the default branch HEAD (batched per org
as a single GraphQL query, aliasing each repo, rather than one REST call per file) and grepped every
`uses: infra-commons/legal/.github/workflows/<file>@<ref>` line across all five reusables
(`legal-review`, `legal-capture-findings`, `annual-review`, `quarterly-review`,
`legal-codebase-scan`).

**One methodology note worth recording because it is the kind of thing that produces a wrong
number: a naive grep over-counts by 5.** `legal-review-reusable.yml` and its four siblings each
carry a header comment showing the caller pattern, e.g. `# uses:
infra-commons/legal/.github/workflows/legal-review-reusable.yml@main`. A regex blind to comment
lines counts `infra-commons/legal` as a caller of itself, once per reusable, always at `@main` —
which is how a first pass here landed on 53 lines / 19 repos before the five doc-comment lines were
excluded. The corrected result:

**Result: 18 caller repos, 48 `uses:` lines. 4 lines (4 `klsjapan-com` repos, review-half only)
track the moving tag `legal-review/v1`. 41 lines are hard SHA pins across 5 distinct SHAs. 3 lines
(`chargingblindly-com/legal`, review + annual + quarterly halves) track `@main` directly.**

This **confirms** the repo count (18), line count (48), and tag-tracker count (4, same four repos)
from #23's 2026-08-09 census. It **corrects** the SHA/main split: #23 said 44 SHA pins and 4
`@main` lines; the fresh count is 41 and 3. `chargingblindly-com/legal`'s `legal-capture-findings`
line is not on `@main` as previously recorded — it is SHA-pinned, like everyone else's capture
call. `legal-review` specifically has 17 caller repos, not 18 — `cashbucket-com/marketing` is the
18th repo overall but calls only `legal-capture-findings`.

| Legal workflow | moving tag | SHA-pinned | @main | callers |
|---|---|---|---|---|
| `legal-review-reusable.yml` | 4 | 12 (all `8f2fb005`) | 1 | 17 |
| `legal-capture-findings-reusable.yml` | 0 | 18 (17× `fb4c92a8`, 1× `705e4457`) | 0 | 18 |
| `annual-review-reusable.yml` | 0 | 3 | 1 | 4 |
| `quarterly-review-reusable.yml` | 0 | 3 | 1 | 4 |
| `legal-codebase-scan-reusable.yml` | 0 | 5 | 0 | 5 |

Distinct SHAs pinned today, and how far behind `main` (HEAD `992e78d`, 2026-08-15) each is:

| SHA | Lines | Committed | Behind `main` |
|---|---|---|---|
| `8f2fb0057fc7…` | 19 | 2026-07-28 | 7 commits |
| `fb4c92a8e536…` | 17 | 2026-08-11 | 3 commits |
| `705e4457e582…` | 3 | 2026-06-11 | 24 commits |
| `767961d42336…` | 1 | 2026-08-11 | 2 commits |
| `ceb32b8ce47a…` | 1 | 2026-06-14 | 23 commits |

`legal-review/v1` still resolves to `8f2fb0057fc7…`, unchanged since #23/#25 were filed — so its lag
against `main` has grown from 3 commits (2026-07-28 reading) to 7 (today), purely because nothing
has moved it, not because anything moved backward.

## What changed since #23 was filed (2026-08-09 → 2026-08-15)

The SHA *set* is not the one #23 recorded, and the gap is dated evidence of drift happening on a
one-week cadence, not a hypothetical:

- #23 recorded `bedf8309…` and `ffa26af8…` as two of the five pinned SHAs. Neither appears in any
  caller today — every line that pinned them has since been bumped by a caller PR. In their place:
  `fb4c92a8…` (17 lines, committed 2026-08-11) and `767961d4…` (1 line, committed 2026-08-11).
  Both landed *after* #23's census and *within this week* — the clearest available proof that a
  caller-pin table is stale within days, not months.
- The bump was uneven even within single repos. `rolliq-com/website` moved its
  `legal-codebase-scan` pin to `767961d4` (2 commits behind) and its `legal-capture-findings` pin to
  `fb4c92a8` (3 commits behind) — both fresh — while its `legal-review` pin is still frozen at
  `8f2fb005` (7 commits behind). Three reusables, three different freshness levels, one repo. SHA
  pinning is not failing to update; it is updating selectively, on whatever schedule each caller's
  own PR cadence happens to produce, and `legal-review` — the one that actually gates merges and
  carries the suppression logic — is not the one getting bumped.
- #24 separately claimed `legal-capture-findings` has "14 SHA-pinned call sites on four different
  SHAs." Fresh count: 18 lines, 2 distinct SHAs. Also stale, independent of #23's numbers — worth
  correcting in #24 directly, not just here.
- Confirmed unchanged: no release workflow exists in `infra-commons/legal` (workflow list is
  exactly `annual-review-reusable.yml`, `auto-assign.yml`, `legal-capture-findings-reusable.yml`,
  `legal-codebase-scan-reusable.yml`, `legal-review-reusable.yml`, `quarterly-review-reusable.yml`,
  `secret-scan.yml`, `tests.yml`); zero GitHub releases; `repos/infra-commons/legal/readme` still
  404s; only `legal-review/v1` and `legal-review/v1.0.0` exist as tags, both still on `8f2fb005`.
  The two tag rulesets (`protect-immutable-tags` 19945085, `protect-immutable-tags` excludes
  `refs/tags/*/v1`; `protect-moving-tags` 19945087, covers only `refs/tags/*/v1`) are unchanged from
  the corrected reading in #25's own thread — re-fetched today, conditions match exactly. The App
  token used here cannot read `bypass_actors` (comes back `null`; that field needs org-owner
  credentials, per the same caveat #25's correcting comment already recorded), so the "the App can
  move it, nothing else can" bypass claim is carried from that org-owner-verified comment rather
  than re-derived here — everything else about the rulesets was independently re-confirmed.
- Spot-checked (not exhaustively re-derived across all 18 repos): `rolliq-com/legal` and
  `rolliq-com/solution-recruitment-reference-check` both still carry `legal-review / gate` as a
  required status check today, confirming #23's two named cases. The full "2 of 18" claim was not
  re-walked repo-by-repo this session — flagging that as a scoping choice, not a re-verification.

## The trade, costed

**Tag-pinning `legal-review`:**
- *One-time build:* a release workflow in `infra-commons/legal` authenticated as the App (only the
  App can move `*/v1` per the ruleset bypass — this was already corrected away from #25's original
  "relax both rulesets" reading, and stays corrected: no operator ruleset change is required, only a
  release mechanism that runs as the right identity).
- *One-time caller migration:* 12 caller PRs to move the SHA-pinned `legal-review` callers
  (`rolliq-com`: website, platform-iac, clients-config, solution-template,
  solution-recruitment-reference-check, marketing, legal, operations, devops — 9 repos;
  `cashbucket-com`: website, legal, operations — 3 repos) from `@8f2fb005` onto `@legal-review/v1`,
  plus one more to switch `chargingblindly-com/legal` from `@main` to the tag for consistency
  (functionally low-risk since it already tracks HEAD, but leaving it on `@main` means it is not
  actually part of "the tag contract" and would keep silently deploying on every merge regardless of
  what this decision settles). 13 PRs total, reviewed by 3 different orgs' own maintainers — this
  repo does not review or merge them.
- *Ongoing cost after migration:* zero caller PRs per fix for the 17 (soon 18 incl. chargingblindly)
  `legal-review` callers. In exchange, every merge to `infra-commons/legal` main plus every tag
  advance reaches all of them with **no per-caller pin review** — which is precisely the condition
  `security#59` was filed against.

**SHA-pinning everything (status quo, formalized):**
- *One-time build:* none beyond the pin-drift verifier, which is needed either way (§below).
- *Ongoing cost:* a caller PR per fix per repo, forever — and per the fresh data above, that
  discipline is already uneven today: `legal-capture-findings` and `legal-codebase-scan` pins are
  visibly getting bumped within days in several repos, while `legal-review` pins sit 7+ commits
  stale in 12 of them. A verifier that flags drift makes this visible; it does not make anyone bump
  the pin.

**Either way, unbuilt:** a pin-drift check. Nothing today compares a caller's pinned SHA against
`main` and says anything. That gap exists regardless of which option wins, and closing it is
independent, low-cost work this repo could do without waiting on #23.

## What this means for #24 (should the four untagged reusables be released at all?)

- If **option 1** (tag `legal-review` only) is chosen: #24 stays answered as it already recommends
  — `annual-review`, `quarterly-review`, `legal-codebase-scan` stay SHA-pinned; `legal-capture-findings`
  is the debatable one, and the fresh numbers make it *cheaper* to reconsider than #24 assumed (18
  SHA-pinned lines across 2 distinct SHAs, not 14 across 4 — half the caller-PR cost, and 17 of
  those 18 lines are already on a 3-commits-behind SHA rather than badly stale). The blocking cost of
  tagging a second family is not the caller-PR count, though — it is extending the App-authenticated
  release mechanism and the required-human-review-on-every-merge burden to a second tag. That is a
  real cost, not a formality, and should be decided on its own once #23's mechanism exists and has
  run at least once for `legal-review`.
- If **option 2** (SHA-pin everything) is chosen: #24 resolves exactly as it already says —
  none of the four get tagged, and the verifier checks pin drift instead of tag presence.
- Either way, #24's own numeric claim ("14 SHA-pinned call sites on four different SHAs") should be
  corrected to today's 18/2 — that correction stands independent of which option wins.

## What this means for #25 (the `legal-review/v1` tag move)

- The **"reaches 4 of 18 repos" fact is reconfirmed exactly**, fresh, today — same four
  `klsjapan-com` repos, review-half only.
- The **ruleset facts are reconfirmed exactly as #25's own correcting comment already fixed them**:
  the tag is not frozen for everyone. `protect-immutable-tags` excludes `refs/tags/*/v1`, so only
  `protect-moving-tags` governs it, and that one has a bypass. The prerequisite is not an operator
  ruleset edit — it is that no release mechanism exists yet, and the identity such a mechanism must
  run as is the App, not `GITHUB_TOKEN`. Nothing this session found changes that reading.
- What's new: the tag's lag against `main` has grown from 3 commits (when #25 was filed) to 7
  (today), simply from sitting still. If option 1 is chosen, that lag is exactly what the release
  mechanism should close on its first run — advancing the tag is not free even then; it needs the
  sequencing below, not a manual move.
- **`chargingblindly-com/legal` already treats "merge to `infra-commons/legal` main" as an instant,
  unreviewed deploy today, independent of #23/#25** — 3 of its 4 lines (`legal-review`,
  `annual-review`, `quarterly-review`) track `@main` directly, with no pin review of any kind. This
  is a live, present-tense analog of the exact failure mode `security#59` found in Group A repos
  (org security-repo stubs pinned `@main`, so a merge *was* the deploy) — except here it is a direct
  caller, not a stub, and it is already true regardless of which delivery-contract option is chosen.
  **Retained as a finding below rather than filed** — see that section.

## Safety and sequencing

`security#59` is the direct precedent, and it is worth restating precisely what it showed rather
than treating it as a general warning: (1) a moving tag created before its target commit was merged
left a window where the tag pointed at unreviewed code; (2) callers that reach a reusable through an
org-local `@main` stub treat *any* merge to the source repo as their deploy, and checking only the
direct-caller graph misses them entirely; (3) a release that adds a signal (`outcome`) and moves only
one of two related tags ships in a state that looks complete but silently can't produce the new
signal. All three are concrete, dated, and already happened once in this fleet on a sibling repo.

Applied here, if option 1 is chosen, the safe order is:

1. **Build the release workflow first, authenticated as the App**, and prove it on a disposable ref
   before touching `legal-review/v1` — create and delete a throwaway `zz-probe/v1` tag through it,
   exactly as suggested in #25's own thread, so the mechanism is validated against the real ruleset
   before anything real depends on it.
2. **Migrate SHA-pinned `legal-review` callers to the tag one org at a time**, not all 13 in one
   batch — `rolliq-com` first (9 repos, largest single blast radius if something's wrong with the
   mechanism), then `cashbucket-com` (3), then `chargingblindly-com` (1, plus its switch off
   `@main`). A bad migration surfaces on the first org's PRs before it reaches the rest.
3. **Only then advance `legal-review/v1` itself**, and only through the proven release mechanism —
   never a manual force-move — so the create-before-merge and partial-multi-tag-race hazards
   `security#59` hit can't recur here. Verify the tag resolves to a real, present action/workflow
   content at the ref before announcing it, not by the ref merely existing.
4. **Build the pin-drift verifier in parallel with all of the above**, not after — it is needed
   regardless of which option wins, and it is the thing that would have made `legal-review`'s current
   7-commit lag visible to an operator without this document.
5. Whatever is chosen, this ships to **17 repos (18 once `chargingblindly-com/legal` is normalized
   onto the tag) on a required check with no per-caller pin review once migrated**. That is the
   number a "just move the tag" instinct is actually pricing.

## Scope note

Read-only throughout: GitHub App installation tokens (read scopes only exercised — repo listing,
tree/content reads, tag/ruleset reads, `compare`), no local clone, no `gh search code` used for
enumeration. No tag was moved, no pin was changed, no ruleset was touched, no caller PR was opened.
This document and its supporting comment on #23 are the only writes made.

## Finding retained for the operator (not filed)

`chargingblindly-com/legal` pins three of its four `infra-commons/legal` reusable calls
(`legal-review`, `annual-review`, `quarterly-review`) at `@main` rather than a SHA or the tag. That
means, right now, independent of anything in #23/#24/#25: any merge to `infra-commons/legal`'s
`main` branch reaches that repo's next PR immediately, with zero pin review — the same shape of
exposure `security#59` found in its Group A repos, except via a direct caller rather than an org
stub. It predates this session and is not something #23 created or would fix by itself (tag-pinning
`legal-review` for everyone else does not change what `@main` already does for this one repo). Worth
a decision on its own — pin it to a SHA, or fold it into whichever tag `legal-review` ends up on —
but that's the operator's call whether it becomes its own issue; not filed from here.
