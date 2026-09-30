"""The reviewer pin, and the output-format contracts a pin move can break.

Written alongside the claude-sonnet-4-6 -> claude-sonnet-5 swap that closed the
generation gap with infra-commons/security's adversarial gate.

The swap itself is three constants. What made it a scoped piece of work is that
all three workflows read the model's output with parsers that assume a shape the
model is merely *asked* for -- Markdown headings in the reviewer, a JSON object
in the capture half, pipe-delimited lines in the scan -- and every one of those
parsers used to answer "I could not read this" with the same value it uses for
"there is nothing here". A model generation that words or formats things
differently therefore turned a blocking gate green rather than red.

That is the same class as the still-open gpt-4o -> gpt-5.5 regression, where
suppressions regex-matching reviewer PROSE let settled false positives back in,
and the same class as the max_tokens gap infra-commons/security#109 found. The
difference is direction: those resurface findings noisily, this one drops them
silently, on a check that is REQUIRED on caller repos.

None of these tests make a live model call, and none of them can tell you what
the pinned model (claude-sonnet-5-5 since infra-commons/meta#1664) actually emits. What they pin is that drift fails loudly instead
of silently -- which is the property that makes the next pin move safe too.
"""
from __future__ import annotations

import json

import pytest

# The exact template SYSTEM_PROMPT asks the model to produce.
CANONICAL_CLEAN = """## Legal findings

### CRITICAL -- legal breach, fix before merge
_(or "None")_

### HIGH -- serious risk, fix before going live
- [src/a.py:1] Something worth fixing before launch.

### MEDIUM -- fix within 90 days
_(or "None")_

### LOW -- best-practice improvements
_(or "None")_

### Summary
Overall risk is low.
"""

CANONICAL_CRITICAL = """## Legal findings

### CRITICAL -- legal breach, fix before merge
- [src/a.py:42] Customer email logged in plain text -- breaches Privacy Act 2020 IPP 5.

### HIGH -- serious risk, fix before going live
_(or "None")_

### MEDIUM -- fix within 90 days
_(or "None")_

### LOW -- best-practice improvements
_(or "None")_

### Summary
One CRITICAL finding.
"""


# ── The pin itself ──────────────────────────────────────────────────────────

# Nothing else in the suite observes `model=`: the fake Anthropic client in
# test_legal_truncation_guard.py accepts **kwargs and ignores them, so a silent
# revert of any of these three constants would not fail a single existing test.
@pytest.mark.parametrize("fixture_name", ["reviewer", "capture", "scan"])
def test_all_three_reviewers_pin_the_same_current_model(fixture_name, request):
    """All three legal reviewers run the same, current model.

    They drifted a full generation behind the security gate once already. The
    value matters less than the three of them agreeing: a swap that updates two
    of three leaves the fleet with reviewers of different capability disagreeing
    about the same diff.
    """
    mod = request.getfixturevalue(fixture_name)
    assert mod.MODEL == "claude-sonnet-5-5"


@pytest.mark.parametrize("fixture_name", ["reviewer", "capture", "scan"])
def test_all_three_reviewers_use_the_same_output_budget(fixture_name, request):
    """Same argument as the model pin above: the three must agree.

    4096 truncated routine reviews (infra-commons/legal#47) -- the pinned model's
    reasoning tokens are billed inside this budget. The ceiling is the SDK's, not
    the model's: a non-streaming call above ~21,300 raises before it is sent.
    """
    assert request.getfixturevalue(fixture_name).MAX_OUTPUT_TOKENS == 16384


@pytest.mark.parametrize(
    "workflow_attr",
    ["WORKFLOW", "CAPTURE_WORKFLOW", "SCAN_WORKFLOW"],
)
def test_the_old_output_ceiling_is_gone_from_every_call_site(workflow_attr):
    """A partial revert must fail here rather than in a caller's required check."""
    import conftest

    src = conftest.extract_reviewer_source(getattr(conftest, workflow_attr))
    assert "max_tokens=4096" not in src


@pytest.mark.parametrize(
    "workflow_attr",
    ["WORKFLOW", "CAPTURE_WORKFLOW", "SCAN_WORKFLOW"],
)
@pytest.mark.parametrize("banned", ["temperature", "top_p", "top_k", "budget_tokens"])
def test_no_sampling_or_thinking_params_at_the_call_sites(workflow_attr, banned):
    """The request shape must stay within what current models accept.

    claude-sonnet-5-5 (like claude-sonnet-5 before it) rejects non-default
    `temperature`, `top_p`, `top_k` and `thinking.budget_tokens` with a 400,
    rejects `thinking: {type: "disabled"}`, and rejects assistant prefill. All three
    call sites pass only model/max_tokens/system/messages, which is why this swap
    needed no request-shape change -- but a later edit adding `temperature=0`
    "for determinism" would 400 every legal gate in the fleet at once, at
    runtime, where nothing else here would catch it.

    Read from the shipped heredoc rather than via inspect.getsource: these
    modules are exec'd from a compiled string, so they carry no retrievable
    source of their own.
    """
    import conftest

    src = conftest.extract_reviewer_source(getattr(conftest, workflow_attr))
    assert banned not in src, f"{workflow_attr} passes {banned} to the model"


# ── The merge gate: has_critical_findings ───────────────────────────────────
#
# This function had ZERO tests before this file, despite being the value the
# `gate` job blocks on.

def test_canonical_critical_response_blocks(reviewer):
    assert reviewer.has_critical_findings(CANONICAL_CRITICAL) is True


def test_canonical_clean_response_passes(reviewer):
    assert reviewer.has_critical_findings(CANONICAL_CLEAN) is False


def test_none_marker_is_not_a_finding(reviewer):
    """The template's own empty-section marker must not read as a finding.

    `_(or "None")_` and `- None` both mean "nothing here". Reading either as a
    CRITICAL finding would block every clean PR in the fleet -- a guard that
    fires on the healthy case is one the operator learns to override.
    """
    for marker in ('_(or "None")_', "- None", "- None.", "- _(None)_"):
        review = CANONICAL_CLEAN.replace('### CRITICAL -- legal breach, fix before merge\n_(or "None")_',
                                         f"### CRITICAL -- legal breach, fix before merge\n{marker}")
        assert reviewer.has_critical_findings(review) is False, marker


@pytest.mark.parametrize(
    "heading",
    [
        "### CRITICAL -- legal breach, fix before merge",  # the template
        "## CRITICAL",                                     # shallower level
        "#### CRITICAL findings",                          # deeper level
        "**CRITICAL**",                                    # bold instead of heading
        "### Critical -- legal breach",                    # different case
    ],
)
def test_critical_finding_is_caught_across_heading_styles(reviewer, heading):
    """Heading style is cosmetic to a model and load-bearing to this parser.

    Before the swap only the exact `### CRITICAL` form matched; every other
    rendering here returned False and PASSED the gate over a real finding.
    """
    review = (
        "## Legal findings\n\n"
        f"{heading}\n"
        "- [src/a.py:42] Personal information sent offshore without a transfer basis.\n\n"
        "### HIGH -- serious risk\n"
        '_(or "None")_\n\n'
        "### Summary\nOne critical issue.\n"
    )
    assert reviewer.has_critical_findings(review) is True


def test_preamble_before_the_findings_does_not_hide_them(reviewer):
    """A conversational lead-in is the most likely benign format drift."""
    review = "Here is my review of the diff you provided.\n\n" + CANONICAL_CRITICAL
    assert reviewer.has_critical_findings(review) is True


def test_asterisk_bullets_are_read_as_findings(reviewer):
    review = CANONICAL_CRITICAL.replace("- [src/a.py:42]", "* [src/a.py:42]")
    assert reviewer.has_critical_findings(review) is True


def test_critical_section_does_not_swallow_later_sections(reviewer):
    """A finding under HIGH must not be attributed to CRITICAL.

    The section capture has to stop at the next heading. If it ran to end of
    response, an empty CRITICAL section followed by any HIGH finding would block
    the PR as CRITICAL -- blocking on the healthy case, in the direction the
    broadened recognizer makes easier to get wrong.
    """
    review = (
        "## Legal findings\n\n"
        "### CRITICAL -- legal breach, fix before merge\n"
        '_(or "None")_\n\n'
        "### HIGH -- serious risk, fix before going live\n"
        "- [src/a.py:7] A real HIGH finding that must not be read as CRITICAL.\n\n"
        "### Summary\nNo critical issues.\n"
    )
    assert reviewer.has_critical_findings(review) is False


# ── The fail-closed guard ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "response",
    [
        "",
        "   \n  \n",
        "I'm sorry, I can't help with that.",
        json.dumps({"findings": [{"severity": "CRITICAL", "title": "x"}]}),
        "The diff looks fine to me, no legal concerns.",
        "LEGAL REVIEW\n\nNothing to report.",
    ],
    ids=["empty", "whitespace", "refusal", "json-instead-of-md", "prose", "no-sections"],
)
def test_unreadable_response_raises_instead_of_reading_as_clean(reviewer, response):
    """The core of this change.

    Every string here used to return False -- indistinguishable from a clean
    review -- and the gate job merged the PR. Note the JSON case especially: a
    model that decides to answer in JSON is not misbehaving, it is answering
    differently, and that is exactly what a generation change does.

    The `gate` job blocks on `needs.legal-review.result == 'failure'`, so this
    raise surfaces as a red required check, not a skipped one.
    """
    with pytest.raises(RuntimeError, match="no recognisable severity section"):
        reviewer.has_critical_findings(response)


def test_well_formed_review_without_a_critical_section_is_believed(reviewer):
    """Fail closed on unreadable, NOT on merely-absent.

    A response carrying HIGH/MEDIUM/LOW/Summary headings but no CRITICAL section
    demonstrably followed the template and simply had nothing critical to say.
    Raising here would turn ordinary clean reviews red across the fleet, which is
    the expensive failure the operator called out.
    """
    review = (
        "## Legal findings\n\n"
        "### HIGH -- serious risk\n"
        "- [src/a.py:1] Worth fixing.\n\n"
        "### MEDIUM -- fix within 90 days\n"
        '_(or "None")_\n\n'
        "### Summary\nNo critical issues.\n"
    )
    assert reviewer.has_critical_findings(review) is False


# ── capture.parse_findings ──────────────────────────────────────────────────

def test_capture_parses_a_well_formed_json_response(capture):
    payload = json.dumps({
        "findings": [{
            "severity": "HIGH",
            "location": "src/a.py:10",
            "title": "Email logged",
            "description": "Customer email written to logs.",
            "category": "pii",
        }]
    })
    findings = capture.parse_findings(payload)
    assert len(findings) == 1
    assert findings[0]["severity"] == "HIGH"


def test_capture_raises_on_a_markdown_fenced_response(capture):
    """The likeliest generation drift for a JSON-emitting prompt.

    A fence alone still parses (the brace scan finds the object inside it), so
    the case that actually breaks is prose containing a brace before the JSON --
    the brace scan then slices from the wrong place and json.loads fails. That
    used to print a warning and return [], recording a clean post-merge scan.
    """
    with pytest.raises(RuntimeError):
        capture.parse_findings('Here is the result: {not actually json at all')


def test_capture_raises_on_a_prose_only_response(capture):
    with pytest.raises(RuntimeError, match="Could not extract a JSON object"):
        capture.parse_findings("No legal issues found in this diff.")


def test_capture_still_returns_empty_on_a_genuinely_empty_response(capture):
    """An empty response has no findings to lose; the max_tokens guard covers
    the truncation case upstream. Raising here would add noise without adding
    signal."""
    assert capture.parse_findings("") == []
    assert capture.parse_findings("   \n ") == []


@pytest.mark.parametrize("payload", [
    {},
    {"issues": [{"severity": "CRITICAL", "title": "x"}]},
    [{"severity": "CRITICAL", "title": "x"}],
])
def test_capture_raises_when_the_findings_key_is_absent(capture, payload):
    """`data.get("findings", [])` read a wrong top-level key as a green 0."""
    with pytest.raises(RuntimeError, match="no top-level 'findings' key"):
        capture.parse_findings(json.dumps(payload))


def test_capture_raises_when_findings_is_not_a_list(capture):
    with pytest.raises(RuntimeError, match="not a list"):
        capture.parse_findings(json.dumps({"findings": None}))


def test_capture_an_explicit_empty_findings_list_is_clean(capture):
    assert capture.parse_findings(json.dumps({"findings": []})) == []


def test_capture_reports_findings_dropped_for_off_schema_severity(capture, capsys):
    payload = json.dumps({"findings": [
        {"severity": "HIGH", "title": "kept"},
        {"severity": "SEVERE", "title": "dropped"},
        {"title": "no severity"},
        "not an object",
    ]})
    findings = capture.parse_findings(payload)
    assert [f["title"] for f in findings] == ["kept"]
    assert "dropped 3 finding(s) with off-schema severity" in capsys.readouterr().out


def test_capture_is_silent_when_nothing_is_dropped(capture, capsys):
    capture.parse_findings(json.dumps({"findings": [{"severity": "LOW", "title": "t"}]}))
    assert "dropped" not in capsys.readouterr().out


def test_capture_step_runs_python_unbuffered():
    """Block-buffered stdout made "Reviewing..." and "Parsed N" flush together,
    reading as a skipped model call."""
    import yaml
    from conftest import CAPTURE_WORKFLOW

    wf = yaml.safe_load(CAPTURE_WORKFLOW.read_text(encoding="utf-8"))
    steps = [s for job in wf["jobs"].values() for s in job.get("steps", [])
             if "python3 << 'PYEOF'" in s.get("run", "")]
    assert len(steps) == 1
    assert steps[0]["env"]["PYTHONUNBUFFERED"] == "1"


# ── scan.parse_findings ─────────────────────────────────────────────────────

def test_scan_parses_pipe_delimited_findings(scan):
    text = (
        "HIGH|src/api/client.py:42|pii|Customer email logged in plain text.\n"
        "LOW|.github/workflows/deploy.yml:18|workflow-security|Mutable action tag.\n"
        "SCAN_COMPLETE"
    )
    findings = scan.parse_findings(text)
    assert [f["severity"] for f in findings] == ["HIGH", "LOW"]


def test_scan_accepts_a_clean_scan_that_reports_completion(scan):
    """Zero findings plus the sentinel is a real clean scan, not drift."""
    assert scan.parse_findings("SCAN_COMPLETE") == []


def test_scan_raises_when_nothing_parsed_and_completion_never_reported(scan):
    """The sentinel has been requested by the prompt all along and thrown away.

    Without it, any reformatted response -- a fence, a preamble, prose -- yielded
    zero findings and a green run, which is indistinguishable from a codebase
    with no legal risks in it.
    """
    with pytest.raises(RuntimeError, match="SCAN_COMPLETE"):
        scan.parse_findings("I reviewed the files and found no issues.")


def test_scan_does_not_raise_when_findings_were_parsed(scan):
    """Requiring the sentinel on the success path would cry wolf.

    A response that produced findings demonstrably parsed; a missing trailer
    there is cosmetic, and failing on it would train an override reflex.
    """
    findings = scan.parse_findings("HIGH|src/a.py:1|pii|Email logged in plain text.")
    assert len(findings) == 1
