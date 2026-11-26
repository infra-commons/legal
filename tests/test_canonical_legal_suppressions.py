"""Properties of the CANONICAL suppressions file itself, run through the shipped matcher.

`test_legal_suppressions.py` covers the matcher with synthetic entries. Nothing
drove the canonical file's own entries, so an entry with no `file_pattern` sat in
it unseen: `anthropic-inference-residency-accepted` applied to every file in every
calling repo, silently dropping cross-border findings on DPAs and privacy notices
(infra-commons/legal#30). An over-matching suppression produces no output at all,
so only a test that names what must still FILE can see it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

CANONICAL = Path(__file__).resolve().parents[1] / ".github" / "legal-review-suppressions.yml"
ENTRIES = yaml.safe_load(CANONICAL.read_text(encoding="utf-8"))["suppressions"]
KNOWN_KEYS = {"id", "file_pattern", "finding_pattern", "reason", "added", "added_by", "expires"}

RESIDENCY_ID = "anthropic-inference-residency-accepted"
RESIDENCY_TITLE = "Cross-border disclosure of personal information to Anthropic (United States)"
RESIDENCY_DESC = "Model inference routes candidate data to a US sub-processor without an APP 8 assessment."


def finding(location: str) -> dict:
    return {"severity": "HIGH", "location": location,
            "title": RESIDENCY_TITLE, "description": RESIDENCY_DESC}


def _entry(entry_id: str) -> dict:
    return next(e for e in ENTRIES if e.get("id") == entry_id)


# ── whole file ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: str(e.get("id")))
def test_every_canonical_entry_sets_both_predicates(entry):
    """An absent predicate is skipped by the matcher, not failed — so a missing
    `file_pattern` is not a narrower rule, it is no path scope at all. Absent is
    legitimate in a repo-local file; in the canonical file, which reaches every
    caller in every org, the scope must be written down."""
    assert entry.get("file_pattern"), f"{entry.get('id')}: no file_pattern"
    assert entry.get("finding_pattern"), f"{entry.get('id')}: no finding_pattern"


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: str(e.get("id")))
def test_every_canonical_entry_uses_only_known_keys(entry):
    """The matcher reads keys with `.get()`, so a typo'd `file_patern` reads as
    absent — the same defect as above, with the key visibly present on the page."""
    assert set(entry) <= KNOWN_KEYS, f"{entry.get('id')}: unknown keys {set(entry) - KNOWN_KEYS}"


# ── anthropic-inference-residency-accepted: scope ────────────────────────────

# The four findings this entry was written to dismiss, at the locations they filed.
IN_SCOPE = [
    "docs/decisions/0001-inference-provider-anthropic.md:1",
    "docs/decisions/0001-inference-provider-anthropic.md:1-58",
    "migrations/0003-inference-residency.md:22",
    "schema/client.schema.json:335",
]

# Where a cross-border transfer finding is the genuinely new concern the entry's own
# reason says must be raised, not dismissed.
OUT_OF_SCOPE = [
    "templates/dpa.md:197",
    "contracts/dpa-customer.md:12",
    "site/privacy.html",
    "site/subprocessors.html",
    "site/terms.html",
    "reviews/2026-Q3-quarterly-legal-review.md:108",
    "src/app.py:10",
    "docs/decisions/0001-inference-provider-anthropic.md.bak",
]


def test_the_residency_finding_text_matches_the_entry_finding_pattern(capture):
    """Canary for the negatives below: with only the finding_pattern, this text IS
    suppressed. So when an out-of-scope location survives, that is the path scope
    working, not a finding text too weak to match anything."""
    entry = _entry(RESIDENCY_ID)
    text_only = {"id": RESIDENCY_ID, "finding_pattern": entry["finding_pattern"]}
    assert capture.is_legal_suppressed(finding("anywhere/at-all.md"), [text_only]) == (
        True, RESIDENCY_ID)


@pytest.mark.parametrize("location", IN_SCOPE)
def test_the_accepted_decision_documents_are_still_suppressed(capture, location):
    assert capture.is_legal_suppressed(finding(location), ENTRIES) == (True, RESIDENCY_ID)


@pytest.mark.parametrize("location", OUT_OF_SCOPE)
def test_a_transfer_finding_outside_the_decision_documents_still_files(capture, location):
    """Asserted against the whole canonical file, not the one entry: a finding on
    a DPA or privacy notice must survive every canonical rule."""
    assert capture.is_legal_suppressed(finding(location), ENTRIES) == (False, None)
