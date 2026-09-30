"""A max_tokens-truncated Anthropic response must fail loud, not read as complete.

infra-commons/security#109 found the sibling gap in adversarial-review.py's
call_anthropic(): a truncated response silently stood in for a complete one,
so a review that ran out of output tokens mid-CRITICAL-section read as clean.
The legal reviewer (this repo's PR gate) and the post-merge capture step make
the same `anthropic.messages.create()` call and, until this guard, neither
checked `stop_reason` either -- a truncated response would return whatever
partial text came back and let the caller parse it as if it were complete:

  * `reviewer.run_review()`      -- has_critical_findings() would miss a
                                    CRITICAL cut off before its bullet.
  * `capture.review_diff()`      -- parse_findings() locates the JSON object
                                    by str.find/rfind on braces; an unbalanced
                                    truncated response fails json.loads() and
                                    silently drops EVERY finding in the batch,
                                    including complete CRITICAL ones that came
                                    before the cut.

Exercised with a fake Anthropic client (no network) since nothing else in this
suite mocks the API -- see conftest.py's `reviewer` / `capture` fixtures for
how the modules are exec'd straight out of the shipped workflow YAML.
"""
from __future__ import annotations

import pytest
from anthropic.types import TextBlock, ThinkingBlock

_UNSET = object()


class _FakeUsage:
    def __init__(self, output_tokens: int):
        self.output_tokens = output_tokens


class _FakeContentBlock:
    # `type` is not decoration: the reviewers discriminate text blocks by it, and a
    # double without one is a double that cannot reproduce infra-commons/legal#47.
    def __init__(self, text: str, block_type: str = "text"):
        self.text = text
        self.type = block_type


class _FakeMessage:
    def __init__(self, text: str = "", stop_reason: str = "end_turn",
                 output_tokens: int = 4096, blocks=_UNSET):
        self.content = [_FakeContentBlock(text)] if blocks is _UNSET else blocks
        self.stop_reason = stop_reason
        self.usage = _FakeUsage(output_tokens)


class _FakeMessages:
    def __init__(self, message: _FakeMessage):
        self._message = message

    def create(self, **kwargs):
        return self._message


class _FakeAnthropicClient:
    def __init__(self, message: _FakeMessage, **kwargs):
        self.messages = _FakeMessages(message)


def _install_fake_client(monkeypatch, mod, message: _FakeMessage) -> None:
    monkeypatch.setattr(
        mod.anthropic, "Anthropic", lambda **kwargs: _FakeAnthropicClient(message)
    )


_CALL_SITES = [("reviewer", "run_review"), ("capture", "review_diff")]


@pytest.mark.parametrize("module,func_name", _CALL_SITES)
def test_truncated_response_raises_instead_of_returning_partial_text(
    module, func_name, request, monkeypatch
):
    mod = request.getfixturevalue(module)
    func = getattr(mod, func_name)
    message = _FakeMessage(
        text='## Legal findings\n### CRITICAL -- legal breach, fix before merge\n- [a.py:1',
        stop_reason="max_tokens",
    )
    _install_fake_client(monkeypatch, mod, message)

    with pytest.raises(RuntimeError, match="truncated"):
        func("fake-api-key", "diff", "", "system prompt")


@pytest.mark.parametrize("module,func_name", _CALL_SITES)
def test_complete_response_is_returned_unchanged(module, func_name, request, monkeypatch):
    mod = request.getfixturevalue(module)
    func = getattr(mod, func_name)
    message = _FakeMessage(
        text='## Legal findings\n### CRITICAL -- legal breach, fix before merge\n_(or "None")_',
        stop_reason="end_turn",
    )
    _install_fake_client(monkeypatch, mod, message)

    assert func("fake-api-key", "diff", "", "system prompt") == message.content[0].text


@pytest.mark.parametrize("stop_reason", ["end_turn", "stop_sequence"])
@pytest.mark.parametrize("module,func_name", _CALL_SITES)
def test_non_truncating_stop_reasons_do_not_raise(
    module, func_name, stop_reason, request, monkeypatch
):
    mod = request.getfixturevalue(module)
    func = getattr(mod, func_name)
    message = _FakeMessage(text="fine", stop_reason=stop_reason)
    _install_fake_client(monkeypatch, mod, message)

    func("fake-api-key", "diff", "", "system prompt")  # must not raise


# ── Refusals: infra-commons/meta#1664 ───────────────────────────────────────
# claude-sonnet-5-5 declines in more safety-classifier categories than
# claude-sonnet-5, as HTTP 200 + stop_reason "refusal". A decline with no text
# already raised in _response_text; a decline carrying PARTIAL text did not, and
# a half-written review with no CRITICAL heading yet parses as clean.

@pytest.mark.parametrize("module,func_name", _CALL_SITES)
def test_refusal_with_partial_text_raises(module, func_name, request, monkeypatch):
    mod = request.getfixturevalue(module)
    func = getattr(mod, func_name)
    message = _FakeMessage(
        text="## Legal findings\n### HIGH -- serious risk\n- [a.py:1] Partial",
        stop_reason="refusal",
    )
    message.stop_details = {"type": "refusal", "category": "general_harms"}
    _install_fake_client(monkeypatch, mod, message)

    with pytest.raises(RuntimeError, match="category=general_harms"):
        func("fake-api-key", "diff", "", "system prompt")


@pytest.mark.parametrize("module", ["reviewer", "capture", "scan"])
@pytest.mark.parametrize(
    "details,expected",
    [
        (None, "unknown"),
        ({"type": "refusal", "category": None}, "unknown"),
        ({"type": "refusal", "category": "cyber"}, "cyber"),
        (type("D", (), {"category": "bio"})(), "bio"),
    ],
    ids=["absent", "null-category", "dict", "object"],
)
def test_refusal_category_never_masks_the_refusal(module, details, expected, request):
    mod = request.getfixturevalue(module)
    message = _FakeMessage(stop_reason="refusal")
    if details is not None:
        message.stop_details = details
    assert mod._refusal_category(message) == expected


# ── Block walking: infra-commons/legal#47 ───────────────────────────────────
# All three reviewers read `message.content[0].text` and the pinned model puts a
# reasoning block first, so every real PR crashed before a review was posted. These
# build REAL SDK objects: the old double had `.text` and no `.type`, and passed
# while production crashed.

_HELPER_SITES = ["reviewer", "capture", "scan"]


def _thinking(text: str = "") -> ThinkingBlock:
    return ThinkingBlock(type="thinking", thinking=text, signature="sig")


def _text(text: str) -> TextBlock:
    return TextBlock(type="text", text=text)


class _UnknownBlock:
    """An unknown block type: the SDK yields a text block carrying that type and
    no usable text, which isinstance() and hasattr() accept and `type` rejects."""
    type = "future_block"
    text = None


@pytest.mark.parametrize("module", _HELPER_SITES)
def test_a_reasoning_block_first_does_not_hide_the_text(module, request):
    """The regression pin for infra-commons/legal#47."""
    mod = request.getfixturevalue(module)
    msg = _FakeMessage(blocks=[_thinking(), _text("## Legal findings")])
    assert mod._response_text(msg) == "## Legal findings"


@pytest.mark.parametrize("module", _HELPER_SITES)
def test_text_blocks_are_concatenated_in_order(module, request):
    mod = request.getfixturevalue(module)
    msg = _FakeMessage(blocks=[_text("first"), _thinking(), _text("second")])
    assert mod._response_text(msg) == "first\nsecond"


@pytest.mark.parametrize(
    "blocks",
    [[_thinking()], [_UnknownBlock()], [_text("   ")], [], None],
    ids=["reasoning-only", "unknown-block-type", "blank-text", "empty-content", "null-content"],
)
@pytest.mark.parametrize("module", _HELPER_SITES)
def test_a_response_with_no_readable_text_raises(module, blocks, request):
    """Fail closed, naming what came back. Returning "" would read as a clean
    review to has_critical_findings() and as zero findings to the other two."""
    mod = request.getfixturevalue(module)
    with pytest.raises(RuntimeError, match="no readable text block"):
        mod._response_text(_FakeMessage(blocks=blocks))


@pytest.mark.parametrize("module,func_name", _CALL_SITES)
def test_call_sites_survive_a_reasoning_block(module, func_name, request, monkeypatch):
    mod = request.getfixturevalue(module)
    _install_fake_client(monkeypatch, mod, _FakeMessage(
        blocks=[_thinking(), _text('## Legal findings\n### CRITICAL\n_(None)_')]))
    assert "Legal findings" in getattr(mod, func_name)("k", "diff", "", "system prompt")


# ── The comment body cannot outgrow what a comment can hold ─────────────────

def test_a_short_review_is_not_clamped(reviewer):
    assert reviewer.clamp_for_comment("## Legal findings") == "## Legal findings"


def test_an_oversized_review_is_clamped_and_says_so(reviewer):
    """A body over 65,536 chars is a 422 post_comment() raises on -- an unclamped
    clean review would block the PR it just cleared."""
    clamped = reviewer.clamp_for_comment("x" * 200_000)
    assert len(clamped) < 65_536
    assert "truncated for display" in clamped


def test_scan_module_execs_cleanly_from_its_workflow_heredoc(scan):
    """Smoke test: `legal-codebase-scan-reusable.yml` had no test coverage at all
    before this file -- the `scan` fixture is new (see conftest.py). Its
    max_tokens guard lives inline in main()'s per-batch loop rather than in a
    standalone function, so it isn't unit-tested the way the other two call
    sites are above; this at least catches the module failing to exec/parse.
    """
    assert hasattr(scan, "parse_findings")
    assert hasattr(scan, "file_issue")
    # This used to assert `parse_findings("not json") == []`, i.e. that an
    # unreadable response was reported as a clean scan. That is the fail-open
    # behaviour the claude-sonnet-5 pin swap made unsafe to keep: output shape is
    # model-generation-dependent, so "I could not read this" and "there is nothing
    # here" must not be the same return value. It now raises; see
    # test_legal_model_pin_and_format.py for the full contract.
    with pytest.raises(RuntimeError, match="SCAN_COMPLETE"):
        scan.parse_findings("not json")
