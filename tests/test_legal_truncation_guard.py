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


class _FakeUsage:
    def __init__(self, output_tokens: int):
        self.output_tokens = output_tokens


class _FakeContentBlock:
    def __init__(self, text: str):
        self.text = text


class _FakeMessage:
    def __init__(self, text: str, stop_reason: str, output_tokens: int = 4096):
        self.content = [_FakeContentBlock(text)]
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


def test_scan_module_execs_cleanly_from_its_workflow_heredoc(scan):
    """Smoke test: `legal-codebase-scan-reusable.yml` had no test coverage at all
    before this file -- the `scan` fixture is new (see conftest.py). Its
    max_tokens guard lives inline in main()'s per-batch loop rather than in a
    standalone function, so it isn't unit-tested the way the other two call
    sites are above; this at least catches the module failing to exec/parse.
    """
    assert hasattr(scan, "parse_findings")
    assert hasattr(scan, "file_issue")
    assert scan.parse_findings("not json") == []
