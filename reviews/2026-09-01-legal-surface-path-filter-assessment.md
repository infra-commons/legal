# The legal-review path filter matches paths, not legal surface

**2026-09-01 · `infra-commons/meta#1188` · `.github/workflows/legal-review-reusable.yml`**

Assessment of the claim that `touches_legal_surface()` decides by path alone and therefore misses
the changes that most need a legal review, plus the change shipped in response.

Caller specifics are kept generic here — this repo is public and the measured PR set belongs to
another org.

---

## 1. The claim, reproduced

A caller repo shipped one feature in four consecutive PRs. The filter's decision on each was
established twice over: by running the *shipped* reviewer (extracted from this workflow's heredoc,
the way `tests/conftest.py` does) over each PR's real changed-file list, and by reading the actual
`legal-review / legal-review` job logs.

| PR | what it implemented | filter | job | log line |
|---|---|---|---|---|
| A | a consent gate, fail closed on both keys | **SKIP** | 14s | `No legal surface in 11 changed file(s)` |
| B | a prompt, a JSON schema, and a call that cannot raise | REVIEW | 58s | `Running legal review (model=…)` |
| C | a spend cap on the same path | **SKIP** | 9s | `No legal surface in 10 changed file(s)` |
| D | a post-delivery read wired into both delivered paths | **SKIP** | 15s | `No legal surface in 6 changed file(s)` |

The claim is exact: three PRs implementing legal controls were skipped, and the one that ran did so
because it added a file under a directory named `schemas` — the token `schema`, which had nothing to
do with why that PR mattered. Delete that one file from its diff and it skips too. Four later PRs in
the same series also skipped.

A skip is invisible from the PR. It posts no comment, sets `has_critical=false` deliberately so the
`gate` job still reports and passes, and takes ~10s. On the PR, "reviewed and found nothing" and
"never looked" are the same green tick.

## 2. Widening the token list cannot fix it

The three skipped PRs touch **17 distinct paths across 27 file-changes**: `src/config.py`,
`src/api/routes/webhooks.py`, `src/workflows/*.py`, `infra/*.tf`, a reusable deploy workflow, a
runbook, and tests. **Not one contains a legal word.** No token short of `src`, `infra` or `docs` —
that is, "review everything" — reaches them.

## 3. Matching the diff *content* is worse, and still misses

The obvious next move is to match the same tokens against the diff rather than the paths. Measured
over that caller's last 60 first-parent changes:

| decision rule | changes reviewed |
|---|---|
| current path filter | 19 / 60 (**32%**) |
| path **or** added-line content | 56 / 60 (**93%**) |

That is roughly a 3× increase in billed reviews *and* in exposure to CRITICAL findings, which block
merge on a required check across the fleet — and it **still skips the spend cap**, whose added lines
contain no token either.

So the finding is stronger than "the vocabulary is too narrow". **Token matching — over paths or
over content — does not identify legal loadedness at all.** Legal loadedness is a property of what a
change does; the one review that ran was a coin landing heads. The card's argument holds, and no
widening was made.

## 4. What shipped

Two optional caller inputs and one legibility fix. All three are **default-inert**: with no caller
passing anything, the decision is identical to before, which is pinned as a property
(`test_default_inputs_change_nothing`) rather than asserted here.

- **`force`** (boolean, default `false`) — review regardless of the path filter. It is only useful
  as a caller *expression*, e.g.
  `force: ${{ contains(github.event.pull_request.labels.*.name, 'legal-review') }}`, which makes it
  a per-PR judgement by the author, who has it. Wired to a literal `true` it degrades to "review
  every PR" — defensible for a low-traffic legal repo, expensive elsewhere.
- **`extra_surface_paths`** (string, default empty) — caller-owned surface substrings, matched by
  the same rule as the built-in tokens. The weaker lever, and honest about it: it is still a path
  list. On the measured set, `src/config.py` would have caught PRs A and C and **still missed D**,
  which touched a different module. It goes stale the moment a new file implements a control.
- **The skip says so.** Both branches now write to `$GITHUB_STEP_SUMMARY`, so the run page states
  which happened — `Legal review SKIPPED … This is not a clean legal review` versus
  `Legal review RAN`. The missing-`ANTHROPIC_API_KEY` early return, the other silent no-review on
  this path, says so too. No PR comment on skip: 17 repos × every PR is noise, and the noise is what
  gets a guard ignored.

`touches_legal_surface()` itself is **unchanged**. Every property guarding it — monotone under
union, fail-closed on an unknown path list, unanchored, case-insensitive, near-miss — is a statement
about that function, and folding caller inputs into it would have quietly restated them all. The
levers are an `OR` on top, in a separate `should_review()`, and are additive-only by property: a
caller can buy itself more review, never less. A lever that could subtract would let a caller
silently disable a gate its own org made required.

### Rejected: an LLM triage pass

A cheap model classifying each diff as legally loaded would address the right property. It was not
taken: it replaces a filter that fails *silently* with one that fails *nondeterministically*, on a
required check, across 17 repos — and a small model answering "not legal" is the same silent miss
with more machinery in front of it.

## 5. Blast radius and rollout

Measured 2026-09-01 with `legal-pin-drift.py` (`unreadable_orgs: []`):

- **17 `legal-review.yml` callers across 4 orgs — 12 on the moving tag `legal-review/v1`, 5
  SHA-pinned.** All 5 are pinned to `c4948d1e`, which is exactly where the tag points, so every
  caller is running identical reviewer code today.
- **The release channel is stopped.** `legal-review/v1` is `c4948d1e`; `main` is 5 commits ahead.
  The release run for the newest is `waiting` on the `legal-release` environment. Merging to `main`
  here reaches no caller until that approval happens — and when it does, it also ships the four
  other stranded commits, including the `claude-sonnet-5` reviewer pin move. That is a real
  behaviour change riding along with this inert one.
- A tag advance reaches the 12 tag-pinned callers. The five SHA-pinned ones — including the caller
  this was measured on — need their own pin bumps.

**Rollback.** Reusable: repoint `legal-review/v1` to `c4948d1e` (App-only, via the release
workflow). Caller: revert the one `with:` line — caller-local and instant. Because the change is
default-inert, the tag advance itself has nothing to roll back.

## 6. Residual, not addressed here

1. **One consumer does not use this reusable at all.** Another org's marketing repo carries a
   bespoke inline copy of `LEGAL_SURFACE_TOKENS` / `touches_legal_surface()`. Nothing shipped here
   reaches it; it has the same defect and needs its own change.
2. **`force` wired to a literal `true` will drift to always-on**, because nobody turns a safety
   input off. The expression form is the one worth reviewing at wiring time.
3. **The step summary is not the PR.** It is legible on the run page, not on the PR timeline, so it
   improves the *diagnosis* of a green tick without changing what the tick looks like. Making the
   check itself distinguish the two would mean a second reported context, which is a branch-ruleset
   change in 17 repos — deliberately not attempted here.
4. **A caller can only force what it thinks to force.** These inputs move the judgement to whoever
   has it; they do not create it. A PR whose author does not notice it is legally loaded is still
   skipped, silently — now with a run-page line saying so.
