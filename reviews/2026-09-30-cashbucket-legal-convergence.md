# Upstreaming a caller's legal surface as reusable inputs

**2026-09-30 · `cashbucket-com/marketing#228` · `.github/workflows/legal-review-reusable.yml`**

Design record for the `extra_review_rules` input, and the handoff that lets cashbucket marketing
converge onto the canonical reviewer and retire its bespoke one.

---

## 1. Why

cashbucket marketing is the fleet's only repo with a **bespoke PR-time legal reviewer**
(`cbtools/legal_reviewer.py` + `.github/workflows/legal-review.yml`). It is already canonical
**post-merge**, through `legal-capture.yml`, so it runs two reviewers built from different lineages.
That half-converged split is what let the two suppression schemas diverge in its
`.github/legal-review-suppressions.yml`. It produced marketing#185, #226 and #227, including a
capture-side entry with no pattern that silently dropped HIGH findings.

The operator ruled on 2026-09-29, choosing "middle" (recorded on marketing#228): sharedinfra upstreams
`LEGAL_SURFACE_TOKENS` and the FMCA/FTA prompt rules as **inputs** to the canonical reusable, and
marketing then converges and retires both files.

## 2. What the canonical reusable needed

| cashbucket's bespoke piece | canonical home | status |
|---|---|---|
| `LEGAL_SURFACE_TOKENS` path filter | `extra_surface_paths` (shipped in #44, meta#1188) | **already there.** Same rule (unanchored, case-folded substring), additive only. No change needed. |
| NZ/AU FTA · FMCA · CCCFA · Privacy · ERA · GST prompt rules, product context, scope boundaries | **new** `extra_review_rules` | this change |
| Its severity examples (e.g. "unlicensed financial advice given" = CRITICAL) | **new**, conditional rubric clause (e) | this change: a console decision, see §4 |

The built-in prompt describes a single company (a recruitment reference-check product). cashbucket
marketing has no `AGENTS.md`/`README.md`/`SOLUTION.yaml`, so `<repo_context>` would be empty and its
marketing copy would be reviewed as a recruitment-AI product. That is why the rules block states that
it **supersedes the Context paragraph** where it describes the organisation, product or customers.

## 3. The design

- `extra_review_rules` is a string input with default `''` and is wired as the env var
  `EXTRA_REVIEW_RULES`. `parse_extra_review_rules` treats whitespace-only input as none. Input over
  16,000 chars **fails** the job rather than being truncated, because a truncated rule set reads as
  clean.
- `_build_system_prompt(jurisdictions, extra_rules="")`:
  - **Empty:** the code path that runs is exactly the one that ran before this change. The prompt's
    SHA-256 for `NZ,AU`, `NZ,JP`, `NZ` and `''` is pinned in the tests to the value computed from
    `main@859767b`.
  - **Set:** a `<caller_rules>` block goes after the law list and before `Focus on:`, and one clause
    goes after the rubric's class list. Nothing else changes, which a test asserts by removing exactly
    those two insertions and comparing the rest to the default prompt.
- Nothing cashbucket-specific is a default. cashbucket's values live only in
  `tests/fixtures/cashbucket-marketing-legal-review.yml`. That file is a complete caller workflow, and
  its tokens and rules are copied from `cashbucket-com/marketing@dfc5354`.
- Trust: the rules come from the caller's workflow on the PR head, the same trust as `jurisdictions`,
  `force` and `extra_surface_paths`. A PR can edit them. That is no worse than today, where the
  bespoke gate runs `cbtools/legal_reviewer.py` from the PR head too. It is also not base-pinned the
  way suppressions are.

## 4. Clause (e): a console decision, not the operator's

The R1 severity rubric (rolliq-com/operations#389) admits exactly four CRITICAL/HIGH classes. None
of them reaches a financial-advice-boundary breach. When `extra_review_rules` is set, and only then,
this change adds:

> Notwithstanding "exactly four" above, for this repository a fifth class qualifies:
> (e) a breach that `<caller_rules>` itself names as CRITICAL or HIGH, occurring now in the diff —
> score it at the severity `<caller_rules>` names.

**Decided by the sharedinfra lane console on 2026-09-30. The operator has not ruled on it.** The
reasoning: a caller's own regulatory surface should be able to carry its own severity. Without
clause (e), convergence would silently reclassify a live FMCA finding to MEDIUM, with nothing
recording that it was ever higher.

It is *not* about preserving a GitHub merge block. Legal review is not a required status check on
cashbucket marketing today. The practical hold is this fleet's merge tooling, which will not
auto-merge a PR with a failing check, required or not (`sharedinfra/scripts/merge-ready.py`
`ci_rollup`). A CRITICAL makes `legal-review / gate` fail.

**One-line revert if the operator disagrees:** in `_build_system_prompt`, delete the line
`template = template.replace(_RUBRIC_ANCHOR, _RUBRIC_ANCHOR + _CALLER_SEVERITY_CLASS)`. The caller
block still ships, and severity reverts to the four canonical classes. Then drop the tests in
`tests/test_legal_caller_rules.py` that assert `(e)` is present.

## 5. Coverage parity (measured, not assumed)

With cashbucket's tokens passed as `extra_surface_paths`, the converged caller reviews a PR whenever
the bespoke gate would. This is a hypothesis property over 500 derandomised path lists shaped like the
marketing tree. The canonical tokens add review on paths containing `migration`, `content`, `blog`,
`marketing`, `eula`, `sub-processor` or `personal-data`, so the rate rises slightly and never falls.
Without the input, the built-in tokens miss `brands/cashbucket/staging/**`, `cbtools/**`, `engine/**`
and `prompts/**`. That is the measured reason the bespoke list exists, and each is pinned.

## 6. cashbucket marketing's side (theirs; not done from this repo)

Consumable once `legal-review/v1` advances past this change (see §7).

1. Replace `.github/workflows/legal-review.yml` wholesale with
   `tests/fixtures/cashbucket-marketing-legal-review.yml` from this repo, minus its leading comment
   block. It calls `...legal-review-reusable.yml@legal-review/v1` with:
   - `jurisdictions: 'NZ,AU'`;
   - its tokens as `extra_surface_paths`;
   - its rules as `extra_review_rules`;
   - `secrets: inherit`, which carries the same `ANTHROPIC_API_KEY` name.
2. **Do not** carry over the old job-level `if: !draft` onto the `uses:` job. A skipped reusable
   means no `gate` job at all. Drafts will be reviewed; that is the price of convergence.
3. Check names change from `Review for legal compliance risk` to `legal-review / legal-review` and
   `legal-review / gate`. Update anything that names the old check, such as protection, dashboards
   or docs.
4. Delete `cbtools/legal_reviewer.py` and `tests/test_legal_reviewer.py`. In `ci.yml`, remove the
   `legal_reviewer` coverage notes and re-baseline the coverage floor, which counted that module.
5. `.github/legal-review-suppressions.yml`:
   - `law_contains`/`finding_contains` become inert, because the canonical reviewer and capture both
     read only `file_pattern`/`finding_pattern`;
   - rewrite the "TWO consumers" header down to one schema;
   - drop the two-schema test with the reviewer's tests;
   - keep both entries; their regex predicates already exist.

   At PR time the canonical reviewer uses suppressions as prompt hints, not as a hard filter.
   Blocking parity holds anyway: both gates block only on CRITICAL, and CRITICAL was never
   suppressible.
6. Expect these deltas:
   - model moves from Haiku 4.5 to `claude-sonnet-5`, so cost per review goes up;
   - Markdown findings replace JSON;
   - a new comment marker, so the old bot comment is left behind once;
   - suppressions become hint-only at PR time;
   - the review rate rises slightly (§5).
7. Update `MARKETING_ENGINE.md` (the legal-agent and suppression-schema sections), then close
   marketing#228.

## 7. Delivery

This reusable ships only through the moving tag `legal-review/v1`. **Merging does not deliver.**
`Tests` on `main` triggers `Release legal reusables`, which waits on the `legal-release`
environment approval, and only that run moves the tag. cashbucket must not adopt the new input until
the tag carries it. Against an older tag the caller does not degrade quietly: GitHub rejects a
`with:` key the reusable does not declare, so the whole workflow fails to start.
