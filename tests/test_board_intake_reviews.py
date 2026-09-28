"""Board intake for the annual/quarterly review reminders (infra-commons/meta#1656).

Both reusables open their issue with `actions/github-script` and then run the same board block as
legal-capture-findings in a separate, later, `continue-on-error` step -- so the filing itself is
untouched and no board failure can stop it. These tests exec that later step's heredoc straight out
of the shipped YAML, the same way conftest.py loads the capture and scan modules.
"""
from __future__ import annotations

import pytest
import yaml

from conftest import CAPTURE_WORKFLOW, REPO_ROOT, _exec_workflow_module
from test_board_intake import _board_block

_REVIEWS = [
    REPO_ROOT / ".github" / "workflows" / "annual-review-reusable.yml",
    REPO_ROOT / ".github" / "workflows" / "quarterly-review-reusable.yml",
]
_each = pytest.mark.parametrize("workflow", _REVIEWS, ids=lambda p: p.stem)


def _steps(workflow):
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    (job,) = jobs.values()
    return job["steps"]


@_each
def test_board_block_is_identical_to_capture(workflow):
    assert _board_block(workflow) == _board_block(CAPTURE_WORKFLOW), (
        "the board-intake block has drifted between filers -- change it in one, copy it to all"
    )


@_each
def test_board_steps_run_after_the_create_and_can_never_fail_the_job(workflow):
    steps = _steps(workflow)
    ids = [s.get("id") or s.get("name") for s in steps]
    create = ids.index("create")
    board = ids.index("Add review issue to board")
    assert create == 0 and ids.index("board-token") > create and board > create
    for step in steps[create + 1:]:
        assert step.get("continue-on-error") is True, f"{step} could turn a filed issue into a red job"
    env = steps[board]["env"]
    assert env["ISSUE_NODE_ID"] == "${{ steps.create.outputs.node_id }}"
    assert env["BOARD_KEY_FORWARDED"] == "${{ env.BOARD_APP_KEY != '' }}"
    assert "core.setOutput('node_id', issue.data.node_id)" in steps[create]["with"]["script"]


@_each
def test_board_token_scope_and_optional_secret(workflow):
    doc = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    token = next(s for s in _steps(workflow) if s.get("id") == "board-token")
    assert token["if"] == "${{ env.BOARD_APP_KEY != '' }}"
    assert token["with"]["permission-organization-projects"] == "write"
    assert token["with"]["permission-issues"] == "read"
    # `on:` parses as True under YAML 1.1 -- see test_board_token_scope.py.
    assert doc[True]["workflow_call"]["secrets"]["INFRA_COMMONS_BOT_PRIVATE_KEY"]["required"] is False


@_each
def test_main_warns_when_the_caller_does_not_forward_the_key(workflow, monkeypatch, capsys):
    mod = _exec_workflow_module(workflow, f"board_{workflow.stem}")
    monkeypatch.setenv("REPO", "chargingblindly-com/legal")
    monkeypatch.setenv("ISSUE_NUMBER", "12")
    monkeypatch.setenv("ISSUE_NODE_ID", "I_rev")
    monkeypatch.setenv("BOARD_APP_TOKEN", "")
    monkeypatch.setenv("BOARD_KEY_FORWARDED", "false")
    mod.main()
    out = capsys.readouterr().out
    assert "::warning title=board intake::issue #12 filed but NOT on the chargingblindly-com board" in out
    assert "does not forward" in out


@_each
def test_main_board_adds_the_created_issue_to_the_repo_owner(workflow, monkeypatch, capsys):
    mod = _exec_workflow_module(workflow, f"board_{workflow.stem}")
    calls = []
    monkeypatch.setattr(mod, "add_to_board", lambda tok, owner, node: calls.append((tok, owner, node)) or (True, "added to board Inbox"))
    monkeypatch.setenv("REPO", "rolliq-com/legal")
    monkeypatch.setenv("ISSUE_NUMBER", "3")
    monkeypatch.setenv("ISSUE_NODE_ID", "I_rev")
    monkeypatch.setenv("BOARD_APP_TOKEN", "board-tok")
    monkeypatch.setenv("BOARD_KEY_FORWARDED", "true")
    mod.main()
    assert calls == [("board-tok", "rolliq-com", "I_rev")]
    assert "::warning" not in capsys.readouterr().out
