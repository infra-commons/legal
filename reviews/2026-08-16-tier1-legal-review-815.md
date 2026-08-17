# Tier 1 first pass — `legal-review` family (infra-commons/meta#815)

**Scope:** `infra-commons/legal`, Tier 1, all four reusable-workflow-family surfaces that make a
model call from PR/push-triggered automation: `legal-review-reusable.yml` (the PR gate),
`legal-capture-findings-reusable.yml` (post-merge capture), `legal-codebase-scan-reusable.yml`
(manual retrospective audit), plus the release/tag machinery (`.github/scripts/*.py`,
`release-legal-review.yml`) read for context. Reviewed at `b752b17` (`origin/main` at the time of
this pass). Security and devops are out of scope for this pass per meta#815.

There is no `.github/actions/` directory in this repo — `find` with a naive `-not -path
'*/.git*'` filter self-excludes `.github` too (`.git` is a path-prefix of `.github`), which read as
"no `.github` at all" until checked against `git ls-files` and the GitHub contents API directly. The
reviewer logic lives inline, as a `python3 << 'PYEOF'` heredoc, inside each `.github/workflows/*
-reusable.yml` file.

## STEP ONE — does `/code-review`'s path/branch/PR targeting work from an unattended agent window?

Not re-tested independently this pass — `infra-commons/security`'s Tier 1 pass (this same card,
`reviews/2026-08-16-tier1-adversarial-review-815.md` in that repo) already tested it directly from an
unattended agent window and found the path argument silently dropped, falling back to an ambient-diff
review of unrelated files. That result is mechanism-level (about the tool, not about `security`'s
content) and there is no reason to expect a different outcome here. This pass used ordinary hand
review throughout, per `docs/code-review-cadence.md` §5's established fallback.

## THE HEADLINE QUESTION — does `legal-review` have the same PR-comment-cache trust gap `security#109`/`#110` found in `adversarial-review.py`?

**No — established by reading, not by analogy. `legal-review-reusable.yml` has no verdict cache of
any kind.** Every PR run that reaches the point of calling the model calls it, unconditionally.

The security bug's shape was: `find_cached_verdict()` scans **every comment on the PR** for a marker
+ a SHA-256 key computed from wholly public inputs, and returns the **first** match — with no check
of `comment.user.login` or any other authorship field — so anyone who can comment on a public PR can
forge a `critical=false` verdict and skip the model call entirely, with the gate treating the PR as
reviewed.

Tracing the equivalent path in `legal-review-reusable.yml`'s embedded reviewer (`main()`, and
everything it calls):

- **No cache lookup exists at all.** There is no function that reads PR comments to decide whether to
  *skip* running the review. Confirmed by reading the full ~250-line reviewer top to bottom and by
  `grep -n "cache\|verdict\|sha256\|hashlib"` across every workflow file in the repo — zero matches
  outside this doc.
- The only thing the reviewer reads back from PR comments is `delete_previous_comments()`, which
  deletes any comment containing the `<!-- legal-review-bot -->` marker before posting the new one.
  This is cosmetic cleanup, not a trust decision — nothing branches on whether that delete succeeds,
  and no comment content is ever parsed back into `has_critical`. (A forged comment carrying the
  marker would just get deleted on the next run — mildly annoying, not a bypass. Not worth a
  same-lane fix; noted for completeness, not filed.)
- **The one PR-controllable-looking input that *is* trusted — repo-local suppressions — is already
  hardened against exactly this class of attack, with the fix attributed inline.**
  `_read_local_suppressions_from_base()` reads `.github/legal-review-suppressions.yml` from
  **`BASE_SHA`** (the PR's actual base commit, passed in by the workflow), never from the checked-out
  working tree — its docstring says explicitly this was changed *because* the working tree on a
  `pull_request` run is the PR's own head, which would let "a PR add a suppression entry and have it
  take effect ON THAT SAME PR." The docstring cites `infra-commons/security`'s
  `adversarial-review.py` base-branch read as the model it followed. Canonical suppressions
  (`infra-commons/legal` main) are fetched independently of anything PR-controlled. `has_critical`
  itself comes straight from parsing the model's own response text for the current run — never from
  anything read back from GitHub.
- `legal-capture-findings-reusable.yml` (the post-merge safety net) has a superficially similar-looking
  step — `open_issue_titles()` / `suppressed_issue_keys()` dedup a new finding against existing GitHub
  Issue titles — but this is a materially different trust boundary, not the same bug:
  1. It runs **post-merge** (`push` to `main`), not on an open PR — there's no "comment on a PR before
     the real review lands" race available to an outside attacker.
  2. Both lookups filter on the `legal` label, which the workflow itself applies via `ensure_labels()`
     — attaching a label to someone else's issue needs triage/write access, not merely the ability to
     open an issue, unlike commenting on a PR which needs no privilege at all on a public repo.
  3. Critically, even a successful title-collision (an issue closed as `wont-fix` for the wrong
     reason) does **not** silently pass: `main()` still counts it as `criticals_already_tracked` and
     unconditionally `sys.exit(1)`s with `"known-open CRITICAL still detected in this diff --
     resolve the issue before merging further changes"` whenever any CRITICAL is present, tracked or
     not. There is no path from "dedup matched" to "exit 0, nothing to see."

**Conclusion: the class of defect does not transfer.** The security bug worked because a cache
*skipped the review* based on unauthenticated PR content computed entirely from public inputs. Nothing
in `legal-review` skips the review based on anything read back from GitHub — it has no memoization
of verdicts across runs at all. This is a real negative result, not an absence of looking: read the
full reviewer, the full capture script, and grepped for the pattern's signature (cache/verdict/hash
lookups) across the whole repo.

## CRITICAL-class gap found, and fixed in this PR

While tracing every model call for the cache question above, checked whether any of the three model
calls in this repo (`legal-review`, `legal-capture-findings`, `legal-codebase-scan`) had the *other*
gap the same motivating context named: `infra-commons/security#109`'s finding that
`adversarial-review.py`'s `call_anthropic()` was missing a truncation guard, so a response cut off at
`max_tokens` read as a **complete, clean review** rather than a partial one. **All three of this
repo's `anthropic.messages.create()` call sites had exactly this gap** — none checked `stop_reason`
before treating the response text as complete:

- **`legal-review-reusable.yml::run_review()`** (the PR-blocking gate). `has_critical_findings()`
  only needs to see one bullet under `### CRITICAL` to return `True`, so a response truncated well
  into or after that section is still caught — but a response cut off before or early within the
  CRITICAL section reads as "no findings," exactly `security#109`'s failure mode, on the one check
  that's a required status on `rolliq-com/legal` and `solution-recruitment-reference-check`.
- **`legal-capture-findings-reusable.yml::review_diff()`** (the post-merge safety net —
  `legal-review`'s own backstop for exactly this kind of miss). Worse mechanically than the Markdown
  case: `parse_findings()` locates the response's JSON object with `str.find('{')` /
  `str.rfind('}')`. A response truncated mid-finding leaves the object unbalanced, so `json.loads()`
  raises, the `except` branch returns `[]`, and **every finding in the batch is silently dropped** —
  including any complete CRITICAL ones that were fully written before the cut. This is the backstop
  for a missed CRITICAL failing exactly the way the thing it backstops could fail.
- **`legal-codebase-scan-reusable.yml`** (manual `workflow_dispatch` audit, lower blast radius — not
  a merge gate, no caller depends on its timeliness). Same unbalanced-JSON mechanism as above, one
  `try/except` layer further out so it already degraded to "0 findings for this batch, logged as an
  incidental JSON-parse warning" rather than crashing the run — but the log message didn't say why.

**Fixed in this PR, same-lane, cheap:** each call site now checks `message.stop_reason == "max_tokens"`
immediately after the API call and raises `RuntimeError` with an explicit explanation before any
parsing happens, rather than letting partial text stand in for a complete review. In
`legal-review-reusable.yml` this fails the `legal-review` job outright, which `gate`'s existing
`REVIEW_RESULT == "failure"` → `BLOCK=true` logic already treats as blocking — no change needed to
the gate job itself. In `legal-capture-findings-reusable.yml` the raise is uncaught in `main()`,
failing the Action run loudly, which is the correct behavior for a required post-merge check. In
`legal-codebase-scan-reusable.yml` the raise is caught by the existing per-batch `except`, now logging
an explicit, honest reason instead of an incidental JSON-parse error.

Added `tests/test_legal_truncation_guard.py` (9 new tests) exercising all three call sites against a
fake Anthropic client (no network): truncated responses raise, complete responses at `end_turn` /
`stop_sequence` return/pass through unchanged. Also added a `scan` fixture to `conftest.py` and one
smoke test — `legal-codebase-scan-reusable.yml` had **no test coverage of any kind** before this pass
(only `legal-review-reusable.yml` and `legal-capture-findings-reusable.yml` were wired into
`conftest.py`'s heredoc-extraction fixtures). The scan module's guard lives inline in `main()`'s
per-batch loop rather than in a standalone function, so it isn't unit-tested at the same granularity
as the other two — noted as a real, if minor, coverage gap rather than glossed over. Full suite:
86 → 95 passing, 0 failing.

## Release mechanism — corrected: it is live, not inert

**This section originally said the release mechanism was inert and this PR's fix would reach no
caller. That was true when written and is false now: `INFRA_COMMONS_BOT_PRIVATE_KEY` was granted to
this repo shortly after, the release ran green, and `legal-review/v1` has already moved once
(`8f2fb005` → `b752b17`, the commit this PR is based on). Corrected in place rather than left
standing, since the original sentence is exactly the kind a reviewer trusts instead of
re-deriving.**

Verified independently, not taken on report:

- `GET /repos/infra-commons/legal/actions/organization-secrets` now lists
  `INFRA_COMMONS_BOT_PRIVATE_KEY`.
- `refs/tags/legal-review/v1` = `refs/heads/main` = `b752b17`, confirmed live via `git ls-remote`.
- The run history (`gh run list --workflow=release-legal-review.yml`) shows a successful
  `workflow_run`-triggered release (18m20s — consistent with waiting on the `legal-release`
  environment's required-reviewer approval before moving the tag) followed 79s later by a
  `schedule`-triggered heartbeat run that failed with `` `legal-review` is unreleased ``. That failure
  is not a new problem: the heartbeat fired *while the release was still mid-approval-wait*, correctly
  observed the tag hadn't moved yet at that instant, and failed loudly as designed — a timing
  artifact of the heartbeat overlapping an in-flight release, not evidence anything is broken.
- Blast radius, measured fresh with `~/repos/sharedinfra/scripts/legal-pin-drift.py` (not
  `gh search code`, which under-reports by org in this lane — see this session's own memory note on
  that): **17 `legal-review.yml` caller lines across 17 repos** (of 18 repos that call any
  `infra-commons/legal` reusable at all):
  - **12 track `legal-review/v1`** (`cashbucket-com/legal`, `cashbucket-com/operations`,
    `cashbucket-com/website`; `klsjapan-com/klsjapan-website`, `klsjapan-com/legal`,
    `klsjapan-com/meta`, `klsjapan-com/nutrition-tracker`; `rolliq-com/devops`, `rolliq-com/legal`,
    `rolliq-com/marketing`, `rolliq-com/operations`, `rolliq-com/website`) — these receive this PR's
    fix the next time `legal-review/v1` advances, gated by the `legal-release` environment's required
    reviewer, not by any missing credential.
  - **1 tracks `@main` directly** — `chargingblindly-com/legal`. This is a *different and more
    exposed* class than the tag-trackers: it has no pin review at all, so it receives this PR's fix
    the instant it merges to `infra-commons/legal`'s `main`, with **no `legal-release` approval gate
    in between**. `chargingblindly-com/legal` also tracks `@main` for `annual-review` and
    `quarterly-review` — a pre-existing pin-hygiene gap this pass did not create and is not in scope
    to fix (cross-lane; `chargingblindly-com`'s own repo), but worth surfacing since it's the single
    most exposed line to anything this repo merges to `main`, not just this PR.
  - **4 are SHA-pinned 10 commits behind main** (`rolliq-com/clients-config`,
    `rolliq-com/platform-iac`, `rolliq-com/solution-recruitment-reference-check`,
    `rolliq-com/solution-template`) and will not receive this fix until each bumps its own pin —
    unaffected by this PR either way.
  - `legal-capture-findings-reusable.yml` and `legal-codebase-scan-reusable.yml` (also fixed in this
    PR) carry no moving tag at all, by design (`infra-commons/legal#23`'s delivery-contract decision
    tag-releases only `legal-review`). Their fixes reach **no caller automatically, regardless of
    release-mechanism status** — only when each caller repo bumps its own SHA pin.

**Consequence for this PR's own risk, re-read with the real delivery path in mind:** the
truncation guard's fail-closed choice (raise and block, rather than silently pass) is still the
correct call — the alternative is exactly the silent-false-clean failure mode this pass exists to
close. But it is no longer a decision made safe by being undeliverable. On the next `legal-review/v1`
advance (after a human approves it), 12 real caller repos' PR gates start failing loudly, instead of
passing silently, on any PR whose legal review happens to truncate at `max_tokens`. On merge to this
repo's `main` — before any approval — `chargingblindly-com/legal`'s gate does the same, immediately.
That is the intended behavior change, not a side effect, and it is the kind of thing the
`legal-release` approval step exists to be told about — which is the point of correcting this section
rather than leaving the "reaches nobody" framing in place for that approver to read.

## Not filed as issues

Per meta#815's capture rules: no GitHub issues opened by this pass. There is no CRITICAL/
security-shaped finding to propose for escalation from this repo's `legal-review` family — the
headline question above resolved negative. The truncation-guard gap was cheap, same-lane, and fixed
directly rather than written up or filed.
