"""Concern-level dedupe (infra-commons/legal#34 ask 2). Ambiguity, a CRITICAL, or a failed
wont-fix re-detection comment all file; a concern match only ever absorbs a near-duplicate."""
from __future__ import annotations

import pytest

PFX = "[Legal][legal-ai]"


def t(sev, loc, text):
    return f"{PFX}[{sev}] {loc} -- {text}"


EMAIL = "Contact address of a named person committed to an operations document"


# ── _concern_parts ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("loc, path", [
    ("docs/a.md:381", "docs/a.md"),
    ("docs/a.md:260-278", "docs/a.md"),
    ("a.md:1-30 and b.md:1-5", "a.md and b.md"),
    ("docs/a.md:1, templates/b.md:53", "docs/a.md, templates/b.md"),
    (".venv", ".venv"),
])
def test_path_strips_every_line_suffix(capture, loc, path):
    assert capture._concern_parts(t("HIGH", loc, EMAIL))[1] == path


@pytest.mark.parametrize("title", [
    t("HIGH", "unknown", EMAIL),
    t("HIGH", "unknown:12", EMAIL),
    t("HIGH", "a.md:3", "PII in log"),          # under three usable words
    f"{PFX}[HIGH] a.md:3 {EMAIL}",              # no " -- " separator
    "Some hand-filed legal issue",
    "",
])
def test_ambiguous_titles_have_no_concern_key(capture, title):
    assert capture._concern_parts(title) is None


# ── concern_match: pairs shaped like the calibration set (synthetic text) ────

def test_same_concern_at_a_shifted_line_matches(capture):
    prior = t("HIGH", "docs/ops.md:46", EMAIL)
    assert capture.concern_match(t("HIGH", "docs/ops.md:381", EMAIL), [prior]) == prior


def test_reworded_near_duplicate_matches(capture):
    prior = t("LOW", "docs/m.md:170", "Ownership of generated deliverables and error-risk "
              "allocation deferred to later review without owner")
    new = t("LOW", "docs/m.md:190", "Ownership of generated output and error-risk "
            "allocation explicitly deferred to later review without owner")
    assert capture.concern_match(new, [prior]) == prior


def test_distinct_concerns_sharing_vocabulary_do_not_match(capture):
    # Shares "personal data", "shared tenant", "without": the 0.2-0.3 band that mixes
    # true duplicates with distinct concerns, which is why the floor sits at 0.5.
    prior = t("HIGH", "docs/s.md:167", "Log rows holding personal data retained in the shared "
              "tenant without verified content control")
    new = t("HIGH", "docs/s.md:185", "Cross-border disclosure of personal data to the shared "
            "tenant without contractual cover")
    assert capture.concern_match(new, [prior]) is None


@pytest.mark.parametrize("prior", [
    t("HIGH", "docs/other.md:46", EMAIL),     # different file
    t("MEDIUM", "docs/r.md:46", EMAIL),       # different severity: an escalation files
])
def test_path_and_severity_must_both_agree(capture, prior):
    assert capture.concern_match(t("HIGH", "docs/r.md:381", EMAIL), [prior]) is None


def test_a_critical_is_never_concern_absorbed(capture):
    prior = t("CRITICAL", "a.md:1", EMAIL)
    assert capture.concern_match(t("CRITICAL", "a.md:9", EMAIL), [prior]) is None


def test_location_only_keys_are_ignored(capture):
    assert capture.concern_match(t("HIGH", "a.md:9", EMAIL), [f"{PFX}[HIGH] a.md:1"]) is None


# ── main(): what gets filed ──────────────────────────────────────────────────

def _harness(capture, monkeypatch, findings, open_titles=(), suppressed=None, comment=None):
    created, comments = [], []
    for k, v in {"ANTHROPIC_API_KEY": "k", "GITHUB_TOKEN": "t", "REPO": "o/r",
                 "BEFORE_SHA": "a" * 40, "AFTER_SHA": "b" * 40}.items():
        monkeypatch.setenv(k, v)
    for name, value in {
        "get_diff": lambda b, a, *_: "diff --git a/x b/x\n+x",
        "get_repo_context": lambda: "",
        "_build_system_prompt": lambda j: "",
        "review_diff": lambda *a: "",
        "parse_findings": lambda raw: findings,
        "ensure_labels": lambda *a: None,
        "open_issue_titles": lambda *a: set(open_titles),
        "suppressed_issue_keys": lambda *a: dict(suppressed or {}),
        "load_legal_suppressions": lambda: [],
        "create_issue": lambda tok, repo, title, body, labels: created.append(title) or {},
        "comment_issue": comment or (lambda tok, repo, n, body: comments.append((n, body))),
    }.items():
        monkeypatch.setattr(capture, name, value)
    monkeypatch.setattr(capture.time, "sleep", lambda s: None)
    capture.main()
    return created, comments


def _f(loc, title=EMAIL, sev="HIGH"):
    return {"severity": sev, "location": loc, "title": title, "category": "pii",
            "description": "desc"}


def test_open_concern_match_files_nothing(capture, monkeypatch):
    created, comments = _harness(capture, monkeypatch, [_f("r.md:381")],
                                 open_titles=[t("HIGH", "r.md:46", EMAIL)])
    assert created == [] and comments == []


def test_wontfix_concern_match_comments_on_the_closed_issue(capture, monkeypatch):
    created, comments = _harness(capture, monkeypatch, [_f("r.md:381")],
                                 suppressed={t("HIGH", "r.md:46", EMAIL): 399})
    assert created == []
    assert comments[0][0] == 399 and "`r.md:381`" in comments[0][1]


def test_a_failed_comment_files_the_finding(capture, monkeypatch):
    def boom(*a):
        raise RuntimeError("422")
    created, _ = _harness(capture, monkeypatch, [_f("r.md:381")],
                          suppressed={t("HIGH", "r.md:46", EMAIL): 399}, comment=boom)
    assert created == [t("HIGH", "r.md:381", EMAIL)]


def test_unrelated_finding_is_filed(capture, monkeypatch):
    other = "Raw recordings stored in a document library without documented retention limit"
    created, comments = _harness(capture, monkeypatch, [_f("r.md:381", other)],
                                 open_titles=[t("HIGH", "r.md:46", EMAIL)],
                                 suppressed={t("HIGH", "r.md:46", EMAIL): 399})
    assert created == [t("HIGH", "r.md:381", other)] and comments == []
