"""The `extra_review_rules` input, and the cashbucket surface it exists to carry.

cashbucket-com/marketing#228 (ruled 2026-09-29, "middle"): cashbucket marketing ran
the fleet's only bespoke PR-time legal reviewer, with its own path tokens and its own
NZ FMCA/FTA prompt rules. Those are upstreamed as INPUTS -- the tokens through the
existing `extra_surface_paths`, the rules through `extra_review_rules` -- so the
caller can converge and retire cbtools/legal_reviewer.py.

Two halves, both pinned here:
  * a caller that passes nothing gets today's prompt, byte for byte -- this reusable
    is a required check on callers that track the moving tag with no per-caller
    review, so the default path must not move;
  * a caller that passes cashbucket's values gets cashbucket's surface: every path
    the bespoke gate reviewed is still reviewed, and its rules reach the model.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

import conftest

FIXTURE = Path(__file__).parent / "fixtures" / "cashbucket-marketing-legal-review.yml"

# SHA-256 of `_build_system_prompt(j)` as shipped on main at 859767b, i.e. BEFORE this
# input existed. A drift here is a behaviour change for every existing caller.
GOLDEN_PROMPT_SHA256 = {
    "NZ,AU": "b75a3a2bbb82f4a4d25ef5c1f88ed8a72249d25958bd5c8c12345c1bbe3ef7e0",
    "NZ,JP": "39ebc67f8e685b5872f95e35d687207f194ea627a8610ceb513b8ee7587db965",
    "NZ": "e7ba7f247faf84704f8e847f529a2c4cef855e7723b26d241f4d85a874beb8af",
    "": "2d8862bfc05acf534286aa000f20dba6b17bfe6f11f1dd9159b97c928c8845ce",
}

# cbtools/legal_reviewer.py LEGAL_SURFACE_TOKENS, verbatim at
# cashbucket-com/marketing@dfc5354 -- the bespoke gate's decision, reproduced as the
# oracle the converged caller must never review less than.
CASHBUCKET_TOKENS = (
    "brand", "article", "messaging", "draft", "brief", "topic", "social",
    "campaign", "newsletter", "welcome", "prompt", "publish", "cbtools",
    "engine", "template",
    "crm", "worker", "dashboard", "contact", "credential", "schema",
    "personal", "pii", "oauth", "xero",
    "legal", "licen", "policy", "policies", "privacy", "terms", "consent",
    "cookie", "retention", "disclaimer", "copyright", "trademark",
    "compliance", "contract", "agreement", "subprocessor", "constitution",
    "operations", "reviews", "gdpr", "dpa",
)


def cashbucket_bespoke_reviews(paths: list[str]) -> bool:
    """cbtools/legal_reviewer.py touches_legal_surface(), same semantics."""
    real = [p for p in paths if p.strip()]
    if not real:
        return True
    return any(t in p.lower() for p in real for t in CASHBUCKET_TOKENS)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture(scope="module")
def caller():
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))["jobs"]["legal-review"]["with"]


# ── the default half: a caller that passes nothing ────────────────────────────

@pytest.mark.parametrize("jurisdictions", sorted(GOLDEN_PROMPT_SHA256))
def test_default_prompt_is_byte_identical_to_before(reviewer, jurisdictions):
    assert _sha(reviewer._build_system_prompt(jurisdictions)) == GOLDEN_PROMPT_SHA256[jurisdictions]


@pytest.mark.parametrize("blank", ["", " ", "\n", "  \n\t "])
def test_blank_rules_are_no_rules(reviewer, blank):
    """A stray newline in a caller's `with:` must not switch the caller block on."""
    assert reviewer.parse_extra_review_rules(blank) == ""
    assert _sha(reviewer._build_system_prompt("NZ,AU", blank)) == GOLDEN_PROMPT_SHA256["NZ,AU"]


def test_default_prompt_has_no_caller_block_and_no_fifth_class(reviewer):
    prompt = reviewer._build_system_prompt("NZ,AU")
    assert "<caller_rules>" not in prompt
    assert "(e)" not in prompt


def test_input_is_declared_optional_with_empty_default_and_wired_to_env():
    wf = yaml.safe_load(conftest.WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML reads the bare `on:` key as boolean True.
    spec = wf[True]["workflow_call"]["inputs"]["extra_review_rules"]
    assert spec == {**spec, "required": False, "default": "", "type": "string"}
    step = next(s for s in wf["jobs"]["legal-review"]["steps"] if s.get("id") == "review")
    assert step["env"]["EXTRA_REVIEW_RULES"] == "${{ inputs.extra_review_rules }}"


def _run_main(reviewer, monkeypatch, rules_env: str | None) -> dict:
    """Run main() with every network/git edge stubbed; return what reached the model."""
    seen: dict = {}
    env = {
        "ANTHROPIC_API_KEY": "k", "GITHUB_TOKEN": "t", "PR_NUMBER": "1",
        "REPO": "o/r", "BASE_SHA": "a" * 40, "HEAD_SHA": "b" * 40,
        "JURISDICTIONS": "NZ,AU", "FORCE_REVIEW": "false", "EXTRA_SURFACE_PATHS": "",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    if rules_env is None:
        monkeypatch.delenv("EXTRA_REVIEW_RULES", raising=False)
    else:
        monkeypatch.setenv("EXTRA_REVIEW_RULES", rules_env)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    def fake_review(api_key, diff, context, system_prompt):
        seen["system_prompt"] = system_prompt
        return (
            "## Legal findings\n\n### CRITICAL -- legal breach, fix before merge\n"
            '_(or "None")_\n\n### HIGH -- serious risk, fix before going live\n_(or "None")_\n\n'
            '### MEDIUM -- fix within 90 days\n_(or "None")_\n\n'
            '### LOW -- best-practice improvements\n_(or "None")_\n\n### Summary\nLow.\n'
        )

    monkeypatch.setattr(reviewer, "get_diff", lambda b, h: "diff --git a/privacy.md b/privacy.md\n+x\n")
    monkeypatch.setattr(reviewer, "get_changed_files", lambda b, h: ["privacy.md"])
    monkeypatch.setattr(reviewer, "get_repo_context", lambda: "")
    monkeypatch.setattr(reviewer, "load_suppressions", lambda token, repo: [])
    monkeypatch.setattr(reviewer, "run_review", fake_review)
    monkeypatch.setattr(reviewer, "delete_previous_comments", lambda *a: None)
    monkeypatch.setattr(reviewer, "post_comment", lambda *a: None)
    reviewer.main()
    return seen


def test_main_without_the_env_var_sends_todays_prompt(reviewer, monkeypatch):
    """End to end through main(), not just the builder: unset env => golden prompt."""
    seen = _run_main(reviewer, monkeypatch, None)
    assert _sha(seen["system_prompt"]) == GOLDEN_PROMPT_SHA256["NZ,AU"]


def test_main_with_the_empty_input_sends_todays_prompt(reviewer, monkeypatch):
    """What GitHub actually hands a caller that passes nothing: the var set to ''."""
    seen = _run_main(reviewer, monkeypatch, "")
    assert _sha(seen["system_prompt"]) == GOLDEN_PROMPT_SHA256["NZ,AU"]


# ── the opt-in half: a caller that passes cashbucket's values ─────────────────

def test_fixture_surface_is_the_bespoke_token_list_verbatim(reviewer, caller):
    assert tuple(reviewer.parse_extra_surface_paths(caller["extra_surface_paths"])) == CASHBUCKET_TOKENS


# Paths shaped like cashbucket marketing's tree, plus arbitrary text.
_cb_segments = st.sampled_from([
    "brands/cashbucket/staging", "cbtools", "engine", "docs", "src", "scripts",
    ".github/workflows", "prompts", "tests", "reviews", "assets/img", "lib",
])
_cb_paths = st.builds(lambda d, f: f"{d}/{f}", _cb_segments, st.text(min_size=1, max_size=30))
path_lists = st.lists(st.one_of(_cb_paths, st.text(max_size=50)), max_size=8)


@given(paths=path_lists)
@settings(max_examples=500)
def test_converged_caller_reviews_everything_the_bespoke_gate_did(reviewer, caller, paths):
    """Convergence must not cost cashbucket review coverage, on any PR."""
    extra = reviewer.parse_extra_surface_paths(caller["extra_surface_paths"])
    if cashbucket_bespoke_reviews(paths):
        assert reviewer.should_review(paths, False, extra) is True


@pytest.mark.parametrize("path", [
    "brands/cashbucket/staging/2026-09-cash-gap.md",
    "prompts/newsletter_welcome.md",
    "cbtools/buffer_publisher.py",
    "engine/weekly.py",
    "cashbucket_core_messaging.md",
])
def test_cashbucket_content_the_builtin_tokens_skip_is_reviewed_with_the_input(reviewer, caller, path):
    """The measured reason the bespoke list exists: canonical tokens miss marketing copy."""
    extra = reviewer.parse_extra_surface_paths(caller["extra_surface_paths"])
    assert reviewer.touches_legal_surface([path]) is False
    assert reviewer.should_review([path], False, extra) is True


def test_cashbucket_rules_reach_the_prompt_in_the_right_slot(reviewer, caller):
    rules = reviewer.parse_extra_review_rules(caller["extra_review_rules"])
    prompt = reviewer._build_system_prompt(caller["jurisdictions"], rules)
    assert rules in prompt
    for must in ("Financial Markets Conduct Act 2013", "Fair Trading Act 1986",
                 "unlicensed financial advice given"):
        assert must in prompt
    # After the law list, before the focus list and the severity rubric.
    at = prompt.index("<caller_rules>")
    assert prompt.index("Common law:") < at < prompt.index("Focus on:") < prompt.index("Exactly four classes")
    assert "supersedes the Context paragraph" in prompt


def test_rules_add_the_fifth_severity_class_after_the_rubric(reviewer, caller):
    """Clause (e): the caller's own CRITICAL/HIGH classes count. Opt-in only."""
    prompt = reviewer._build_system_prompt("NZ,AU", caller["extra_review_rules"])
    e = prompt.index("(e) a breach that <caller_rules> itself names as CRITICAL or HIGH")
    assert prompt.index("(d) an injection path") < e < prompt.index("Score MEDIUM at most")


def test_opted_in_prompt_is_the_default_plus_only_the_two_insertions(reviewer):
    """Nothing else in the prompt moves when a caller opts in."""
    rules = "Context: X Ltd.\n- Some Act s1: breach is CRITICAL."
    base = reviewer._build_system_prompt("NZ,AU")
    opted = reviewer._build_system_prompt("NZ,AU", rules)
    block = reviewer._CALLER_RULES_BLOCK.replace("%%CALLER_RULES%%", rules)
    stripped = opted.replace(block, "", 1).replace(reviewer._CALLER_SEVERITY_CLASS, "", 1)
    assert stripped == base


def test_main_passes_the_rules_to_the_model(reviewer, monkeypatch, caller):
    seen = _run_main(reviewer, monkeypatch, caller["extra_review_rules"])
    assert caller["extra_review_rules"].strip() in seen["system_prompt"]
    assert "(e) a breach that <caller_rules>" in seen["system_prompt"]


def test_oversize_rules_fail_rather_than_truncate(reviewer):
    with pytest.raises(ValueError, match="Refusing to truncate"):
        reviewer.parse_extra_review_rules("x" * (reviewer.MAX_EXTRA_RULES_CHARS + 1))
    assert reviewer.parse_extra_review_rules("x" * reviewer.MAX_EXTRA_RULES_CHARS)


def test_fifth_class_refuses_a_moved_rubric_anchor(reviewer, monkeypatch):
    """A rubric rewording must fail loudly, never silently drop the caller's class."""
    monkeypatch.setattr(reviewer, "_RUBRIC_ANCHOR", "text that is not in the rubric\n")
    with pytest.raises(RuntimeError, match="anchor"):
        reviewer._build_system_prompt("NZ,AU", "Context: X Ltd.")
