"""Properties of the legal suppression matcher.

This function decides whether a legal finding is filed as an issue at all, so a
weakening here is invisible by construction: a suppressed finding and a finding
that was never detected produce identical output — nothing.

That is not hypothetical. An entry carrying neither pattern acted as a wildcard
and silently dropped three HIGH findings, one of them plaintext PII, in
`cashbucket-com/marketing` between 2026-07-17 and 2026-07-30, under a rule whose
`id` scoped it to cloud account IDs. Every property below is written to catch a
weakening in that direction.

The matcher lives in `legal-capture-findings-reusable.yml`, which had no test
coverage at all before this file — the reviewer beside it was well covered,
which is exactly why the gap was not obvious.
"""
from __future__ import annotations

import pytest


def finding(severity="HIGH", location="src/app.py", title="Plaintext PII stored",
            description="User records are written unencrypted."):
    return {
        "severity": severity,
        "location": location,
        "title": title,
        "description": description,
    }


# ── item 1: an entry constraining nothing is invalid, not a wildcard ──────────


def test_an_entry_with_no_patterns_does_not_suppress(capture):
    """THE regression. Both keys absent used to fall through both `continue`s
    and return True for every finding at every severity."""
    sup = [{"id": "cloud-account-ids-are-not-secrets"}]
    assert capture.is_legal_suppressed(finding(), sup) == (False, None)


def test_the_marketing_incident_finding_is_no_longer_dropped(capture):
    """The exact shape that dropped a plaintext-PII HIGH finding: a suppression
    written in the OTHER reviewer's substring schema, carrying neither key this
    matcher reads."""
    sup = [{"id": "azure-subscription-ids", "match": "subscription id", "reason": "not a secret"}]
    suppressed, rule = capture.is_legal_suppressed(
        finding(severity="HIGH", title="Plaintext PII in customer export"), sup
    )
    assert suppressed is False and rule is None


def test_an_entry_with_no_patterns_is_warned_about_not_just_skipped(capture, capsys):
    """A drifted suppressions file must not be silent. Skipping without saying so
    leaves 'my suppressions work' and 'my suppressions are being ignored'
    rendering identically."""
    capture.is_legal_suppressed(finding(), [{"id": "drifted-entry"}])
    err = capsys.readouterr().err
    assert "drifted-entry" in err
    assert "neither file_pattern nor finding_pattern" in err


@pytest.mark.parametrize("sup", [
    {"id": "x", "file_pattern": "", "finding_pattern": ""},
    {"id": "x", "file_pattern": None, "finding_pattern": None},
    {"id": "x"},
])
def test_empty_and_absent_patterns_are_both_treated_as_no_constraint(capture, sup):
    """`""` and absent must behave the same. A truthiness check that accepted one
    and rejected the other would leave half the hole open."""
    assert capture.is_legal_suppressed(finding(), [sup]) == (False, None)


# ── item 1, the other direction: real entries must still suppress ─────────────


def test_a_file_pattern_only_entry_still_suppresses(capture):
    """One pattern is a real constraint. Over-correcting to 'both required'
    would break every existing single-pattern entry in the fleet."""
    sup = [{"id": "vendor-boilerplate", "file_pattern": r"^vendor/"}]
    assert capture.is_legal_suppressed(finding(location="vendor/x.py"), sup) == (
        True, "vendor-boilerplate")


def test_a_finding_pattern_only_entry_still_suppresses(capture):
    sup = [{"id": "known-copy", "finding_pattern": "boilerplate licence header"}]
    f = finding(title="Boilerplate licence header", description="MIT header present.")
    assert capture.is_legal_suppressed(f, sup) == (True, "known-copy")


def test_both_patterns_must_match_when_both_are_present(capture):
    sup = [{"id": "narrow", "file_pattern": r"^vendor/", "finding_pattern": "licence"}]
    assert capture.is_legal_suppressed(
        finding(location="src/app.py", title="licence"), sup)[0] is False
    assert capture.is_legal_suppressed(
        finding(location="vendor/a.py", title="unrelated"), sup)[0] is False


def test_an_unusable_entry_does_not_stop_a_later_valid_one_matching(capture):
    """Order independence: skipping the bad entry must `continue`, not `return`."""
    sup = [{"id": "junk"}, {"id": "real", "file_pattern": r"^vendor/"}]
    assert capture.is_legal_suppressed(finding(location="vendor/x.py"), sup) == (True, "real")


def test_an_invalid_regex_is_still_skipped_rather_than_raising(capture):
    sup = [{"id": "bad-regex", "file_pattern": "([unclosed"}]
    assert capture.is_legal_suppressed(finding(), sup) == (False, None)


# ── item 2: the documented CRITICAL cap, now actually enforced ────────────────


def test_a_critical_finding_is_never_suppressed_even_by_an_exact_match(capture):
    """The canonical file has always documented this cap; nothing enforced it,
    because the matcher never read `severity`. A documented control that nothing
    executes is worse than an absent one — it is believed to be holding."""
    sup = [{"id": "accepted", "file_pattern": r".*", "finding_pattern": r".*"}]
    assert capture.is_legal_suppressed(finding(severity="CRITICAL"), sup) == (False, None)


@pytest.mark.parametrize("sev", ["critical", "Critical", "CRITICAL", " CRITICAL "])
def test_the_critical_cap_is_case_and_whitespace_insensitive(capture, sev):
    """Severity arrives from model output. A cap that only matched one casing
    would be bypassable by the finding's own text."""
    sup = [{"id": "accepted", "file_pattern": r".*"}]
    assert capture.is_legal_suppressed(finding(severity=sev.strip()), sup) == (False, None)


@pytest.mark.parametrize("sev", ["HIGH", "MEDIUM", "LOW"])
def test_non_critical_severities_are_still_suppressible(capture, sev):
    """The cap is at CRITICAL only. Capping everything would make the whole
    suppression mechanism dead code — a filter that never matches."""
    sup = [{"id": "accepted", "file_pattern": r".*"}]
    assert capture.is_legal_suppressed(finding(severity=sev), sup) == (True, "accepted")


def test_a_missing_severity_is_still_suppressible(capture):
    """Absent severity is treated as LOW by the caller, so it must not be caught
    by the CRITICAL cap — that would be a silent widening of the cap."""
    f = {"location": "a.py", "title": "t", "description": "d"}
    assert capture.is_legal_suppressed(f, [{"id": "a", "file_pattern": r".*"}]) == (True, "a")


# ── item 2, review side: the prompt hint carries the carve-out ────────────────


def test_the_prompt_hint_tells_the_model_criticals_are_never_accepted(reviewer):
    context = reviewer.build_suppression_context(
        [{"id": "vendor-boilerplate", "file_pattern": r"^vendor/"}]
    )
    assert "NEVER applies to CRITICAL" in context


def test_the_prompt_hint_ignores_entries_that_constrain_nothing(reviewer):
    """An unusable entry contributing a hint would suppress by suggestion what it
    cannot suppress by rule — the two halves must agree on which entries exist."""
    context = reviewer.build_suppression_context([{"id": "drifted-entry"}])
    assert context == ""


def test_the_prompt_hint_still_lists_real_entries(reviewer):
    context = reviewer.build_suppression_context(
        [{"id": "vendor-boilerplate", "file_pattern": r"^vendor/"}]
    )
    assert "vendor boilerplate" in context
