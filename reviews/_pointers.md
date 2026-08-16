# Review pointer — infra-commons fleet code-review scoping

State for `infra-commons/meta#815`'s fleet code-review scoping work. Extends the pattern used by the
rolliq platform cadence (`docs/reviews-rolliq/_pointers.md` in `sharedinfra`) with an org column,
since this pass spans repos rather than staying inside one. Same shape as `infra-commons/security`'s
`reviews/_pointers.md`, which this repo's row-format mirrors.

A session **reads** this file to know what has already been reviewed and at which SHA, and **writes**
a row back before it ends. Nothing else records that a review happened.

Tier 1 (`security`, `legal`, `devops`) is tracked at reusable-workflow-family granularity — the
composite-action level, not per-repo — per meta#815. meta#815 names `legal/legal-review` as this
repo's tracked family; `legal-capture-findings` and `legal-codebase-scan` are included below too
since this pass read and fixed a matching defect class in both while tracing the headline question.
Tier 2 (control-plane repos) will be added here per-repo if/when that tier starts.

| org | repo | area | last-reviewed SHA | date | findings |
|---|---|---|---|---|---|
| `infra-commons` | `legal` | `legal-review` (PR gate, `.github/workflows/legal-review-reusable.yml`) | `b752b17` | 2026-08-16 | [2026-08-16-tier1-legal-review-815.md](2026-08-16-tier1-legal-review-815.md) |
| `infra-commons` | `legal` | `legal-capture-findings` (post-merge, `.github/workflows/legal-capture-findings-reusable.yml`) | `b752b17` | 2026-08-16 | [2026-08-16-tier1-legal-review-815.md](2026-08-16-tier1-legal-review-815.md) |
| `infra-commons` | `legal` | `legal-codebase-scan` (manual audit, `.github/workflows/legal-codebase-scan-reusable.yml`) | `b752b17` | 2026-08-16 | [2026-08-16-tier1-legal-review-815.md](2026-08-16-tier1-legal-review-815.md) |

**Not covered by this pass:** `security`, `devops` — out of scope per meta#815 (tracked in their own
repos' `reviews/_pointers.md`; see `infra-commons/security`'s for the `adversarial-review` and
`capture-findings` rows). `annual-review-reusable.yml`, `quarterly-review-reusable.yml`,
`auto-assign.yml`, `secret-scan.yml`, and the release/tag scripts under `.github/scripts/` were read
for context (release-mechanism status, delivery-contract shape) but not reviewed line-by-line this
pass. Tier 2 control-plane repos are unstarted; meta#815 notes it is unverified whether they're
already covered by routine session activity or genuinely unreviewed.

**Caution for the next reader:** `legal-review/v1`'s moving tag currently equals `main` at the SHA
above — the release mechanism is **live** (`INFRA_COMMONS_BOT_PRIVATE_KEY` was granted 2026-08-16;
see the findings doc's "Release mechanism" section for how this was verified, and for the corrected
blast-radius count). A "last-reviewed SHA" here being on `main` still does not by itself mean a fix
has reached every caller: 12 of 17 `legal-review.yml` callers track the tag (reached on the next
tag-advance, gated by the `legal-release` environment's required reviewer), 1
(`chargingblindly-com/legal`) tracks `@main` directly (reached on merge to `main`, no approval gate),
and 4 are SHA-pinned behind and reached only when that caller bumps its own pin.
`legal-capture-findings` and `legal-codebase-scan` carry no moving tag at all and reach a caller only
via that caller's own SHA-pin bump, regardless of this repo's release-mechanism status.
