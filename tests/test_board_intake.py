"""Tests for the board-add path added in infra-commons/meta#661.

`add_to_board` is the single function that decides whether a newly-filed HIGH finding reaches the
org's GitHub Project Inbox. Every scenario here asserts the same shape: on any failure, it returns
`(False, <reason>)` — never raises, never touches anything the rest of the capture script depends
on for its exit code. That's the property the whole feature leans on: it must be safe to ship into
every org today, before a single one of them has provisioned the App-token secret.

Mocks at the `_board_graphql` seam (the capture script's own GraphQL request/response boundary)
rather than touching `httpx` directly — same style as `tests/test_legal_suppressions.py`'s use of
the `capture` fixture from conftest.py, which execs the reviewer straight out of its shipped
workflow heredoc rather than a standalone copy.
"""
from __future__ import annotations

import textwrap

from conftest import CAPTURE_WORKFLOW, SCAN_WORKFLOW

_FIELDS_OK = {
    "repositoryOwner": {
        "projectV2": {
            "id": "PVT_project",
            "closed": False,
            "fields": {
                "nodes": [
                    {
                        "__typename": "ProjectV2SingleSelectField",
                        "id": "FIELD_status",
                        "name": "Status",
                        "options": [
                            {"id": "OPT_inbox", "name": "Inbox"},
                            {"id": "OPT_doing", "name": "Doing"},
                        ],
                    }
                ]
            },
        }
    }
}


def _queue(monkeypatch, capture, *responses):
    """Monkeypatch `_board_graphql` to return each of `responses` in order, one per call."""
    calls = list(responses)

    def fake(token, query, variables):
        assert calls, "add_to_board made more GraphQL calls than the test expected"
        return calls.pop(0)

    monkeypatch.setattr(capture, "_board_graphql", fake)


# ── Owner topology ───────────────────────────────────────────────────────────────

def test_owner_project_number_covers_the_fleet(capture):
    # The five orgs this mechanism is meant for — see projects_topology.py in sharedinfra.
    assert set(capture.OWNER_PROJECT_NUMBER) == {
        "infra-commons", "rolliq-com", "cashbucket-com", "klsjapan-com", "chargingblindly-com",
    }


def test_unknown_owner_degrades_without_any_graphql_call(capture, monkeypatch):
    def fail(*a, **k):
        raise AssertionError("should not reach GraphQL for an owner outside the topology table")
    monkeypatch.setattr(capture, "_board_graphql", fail)

    ok, msg = capture.add_to_board("tok", "some-other-org", "I_abc")
    assert ok is False
    assert "not in the board topology" in msg


# ── Field-map read failures ──────────────────────────────────────────────────────

def test_field_map_read_failure_degrades(capture, monkeypatch):
    _queue(monkeypatch, capture, None)  # _board_graphql itself returned None (network/auth/GraphQL error)
    ok, msg = capture.add_to_board("tok", "infra-commons", "I_abc")
    assert ok is False
    assert "could not read project" in msg


def test_closed_project_degrades(capture, monkeypatch):
    closed = {"repositoryOwner": {"projectV2": {"id": "PVT_x", "closed": True, "fields": {"nodes": []}}}}
    _queue(monkeypatch, capture, closed)
    ok, msg = capture.add_to_board("tok", "infra-commons", "I_abc")
    assert ok is False
    assert "closed" in msg


def test_missing_status_field_degrades(capture, monkeypatch):
    no_status = {
        "repositoryOwner": {"projectV2": {"id": "PVT_x", "closed": False, "fields": {"nodes": []}}}
    }
    _queue(monkeypatch, capture, no_status)
    ok, msg = capture.add_to_board("tok", "infra-commons", "I_abc")
    assert ok is False
    assert "Status field" in msg


def test_missing_inbox_option_degrades(capture, monkeypatch):
    no_inbox = {
        "repositoryOwner": {
            "projectV2": {
                "id": "PVT_x", "closed": False,
                "fields": {"nodes": [{
                    "__typename": "ProjectV2SingleSelectField", "id": "FIELD_status",
                    "name": "Status", "options": [{"id": "OPT_doing", "name": "Doing"}],
                }]},
            }
        }
    }
    _queue(monkeypatch, capture, no_inbox)
    ok, msg = capture.add_to_board("tok", "infra-commons", "I_abc")
    assert ok is False
    assert "Inbox option" in msg


# ── Mutation failures ─────────────────────────────────────────────────────────────

def test_add_item_failure_degrades(capture, monkeypatch):
    _queue(monkeypatch, capture, _FIELDS_OK, None)  # fields OK, addProjectV2ItemById call failed
    ok, msg = capture.add_to_board("tok", "infra-commons", "I_abc")
    assert ok is False
    assert "addProjectV2ItemById" in msg


def test_set_status_failure_still_reports_added_but_not_ok(capture, monkeypatch):
    add_ok = {"addProjectV2ItemById": {"item": {"id": "PVTI_new"}}}
    _queue(monkeypatch, capture, _FIELDS_OK, add_ok, None)  # set-Status call failed
    ok, msg = capture.add_to_board("tok", "infra-commons", "I_abc")
    assert ok is False
    assert "Status" in msg


# ── Success ─────────────────────────────────────────────────────────────────────

def test_success_path(capture, monkeypatch):
    add_ok = {"addProjectV2ItemById": {"item": {"id": "PVTI_new"}}}
    set_ok = {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "PVTI_new"}}}
    _queue(monkeypatch, capture, _FIELDS_OK, add_ok, set_ok)
    ok, msg = capture.add_to_board("tok", "infra-commons", "I_abc")
    assert ok is True
    assert "Inbox" in msg


def test_success_path_never_raises_even_with_extra_unused_fields(capture, monkeypatch):
    # A project with unrelated fields (e.g. Priority) alongside Status must not confuse the lookup.
    fields = {
        "repositoryOwner": {
            "projectV2": {
                "id": "PVT_x", "closed": False,
                "fields": {"nodes": [
                    {"__typename": "ProjectV2FieldCommon", "id": "FIELD_priority", "name": "Priority"},
                    _FIELDS_OK["repositoryOwner"]["projectV2"]["fields"]["nodes"][0],
                ]},
            }
        }
    }
    add_ok = {"addProjectV2ItemById": {"item": {"id": "PVTI_new"}}}
    set_ok = {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "PVTI_new"}}}
    _queue(monkeypatch, capture, fields, add_ok, set_ok)
    ok, _msg = capture.add_to_board("tok", "rolliq-com", "I_abc")
    assert ok is True


# ── Wiring: create_issue's return value, and main()'s severity gate ──────────────

def test_create_issue_returns_the_response_json(capture, monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"number": 42, "node_id": "I_xyz"}

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(capture.httpx, "Client", lambda **k: _Client())
    result = capture.create_issue("tok", "infra-commons/legal", "title", "body", ["legal"])
    assert result == {"number": 42, "node_id": "I_xyz"}


def test_board_add_covers_every_severity_capture_files(capture):
    # infra-commons/meta#1656 widened #661's HIGH-only scope: every issue this script files goes
    # on the board. `main()` files CRITICAL and HIGH individually (MEDIUM/LOW are advisory-only
    # log lines, not issues), so this set must equal that one. Changing either is a decision.
    assert capture.BOARD_ADD_SEVERITIES == {"CRITICAL", "HIGH"}


# ── report_board: every outcome but success is a loud ::warning, and nothing raises ──

_ISSUE = {"number": 7, "node_id": "I_abc"}


def test_report_board_no_key_forwarded_warns_and_names_the_caller_gap(capture, capsys):
    assert capture.report_board("", False, "cashbucket-com", _ISSUE) is False
    out = capsys.readouterr().out
    assert out.startswith("::warning title=board intake::issue #7 filed but NOT on the cashbucket-com board")
    assert "does not forward INFRA_COMMONS_BOT_PRIVATE_KEY" in out


def test_report_board_key_forwarded_but_no_token_is_a_different_message(capture, capsys):
    # Absent is not unreadable: a forwarded key whose token didn't mint is a broken install,
    # not a caller that never wired the key up. The two must not read the same.
    assert capture.report_board("", True, "cashbucket-com", _ISSUE) is False
    out = capsys.readouterr().out
    assert "::warning" in out
    assert "did not mint" in out
    assert "does not forward" not in out


def test_report_board_failed_add_warns_with_the_reason(capture, monkeypatch, capsys):
    _queue(monkeypatch, capture, None)  # field map unreadable
    assert capture.report_board("tok", True, "infra-commons", _ISSUE) is False
    out = capsys.readouterr().out
    assert "::warning" in out and "could not read project" in out


def test_report_board_swallows_an_unexpected_exception(capture, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(capture, "add_to_board", boom)
    assert capture.report_board("tok", True, "infra-commons", _ISSUE) is False
    assert "unexpected error: kaboom" in capsys.readouterr().out


def test_report_board_missing_node_id_warns(capture, capsys):
    assert capture.report_board("tok", True, "infra-commons", {"number": 7}) is False
    assert "no node_id" in capsys.readouterr().out


def test_report_board_success_is_not_a_warning(capture, monkeypatch, capsys):
    monkeypatch.setattr(capture, "add_to_board", lambda *a: (True, "added to board Inbox"))
    assert capture.report_board("tok", True, "infra-commons", _ISSUE) is True
    out = capsys.readouterr().out
    assert "::warning" not in out and "#7 added to board Inbox" in out


# ── main(): a board failure never stops or fails the filing ─────────────────────

def _capture_main_harness(capture, monkeypatch, findings, board_calls, created):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("REPO", "cashbucket-com/legal")
    monkeypatch.setenv("BEFORE_SHA", "a" * 40)
    monkeypatch.setenv("AFTER_SHA", "b" * 40)
    monkeypatch.setenv("BOARD_APP_TOKEN", "board-tok")
    monkeypatch.setenv("BOARD_KEY_FORWARDED", "true")
    for name, value in {
        "get_diff": lambda b, a: "diff --git a/x b/x\n+x",
        "get_repo_context": lambda: "",
        "_build_system_prompt": lambda j: "",
        "review_diff": lambda *a: "",
        "parse_findings": lambda raw: findings,
        "ensure_labels": lambda *a: None,
        "open_issue_titles": lambda *a: set(),
        "suppressed_issue_keys": lambda *a: set(),
        "load_legal_suppressions": lambda: [],
    }.items():
        monkeypatch.setattr(capture, name, value)
    monkeypatch.setattr(capture.time, "sleep", lambda s: None)

    def fake_create(token, repo, title, body, labels):
        created.append(title)
        return {"number": len(created), "node_id": f"I_{len(created)}"}

    def failing_board(token, owner, node_id):
        board_calls.append((owner, node_id))
        raise RuntimeError("board is down")

    monkeypatch.setattr(capture, "create_issue", fake_create)
    monkeypatch.setattr(capture, "add_to_board", failing_board)


def _finding(sev, loc):
    return {"severity": sev, "location": loc, "title": "t", "category": "c",
            "description": "d", "recommendation": "r"}


def test_capture_main_files_every_issue_and_exits_clean_when_the_board_is_down(
        capture, monkeypatch, capsys):
    created, board_calls = [], []
    _capture_main_harness(capture, monkeypatch,
                          [_finding("HIGH", "a.md:1"), _finding("HIGH", "b.md:2")],
                          board_calls, created)
    capture.main()  # no SystemExit: a board failure never changes the exit code
    assert len(created) == 2
    assert board_calls == [("cashbucket-com", "I_1"), ("cashbucket-com", "I_2")]
    assert capsys.readouterr().out.count("::warning title=board intake::") == 2


def test_capture_main_board_adds_a_critical_too(capture, monkeypatch):
    created, board_calls = [], []
    _capture_main_harness(capture, monkeypatch, [_finding("CRITICAL", "a.md:1")],
                          board_calls, created)
    try:
        capture.main()
    except SystemExit as exc:  # the pre-existing CRITICAL gate, unrelated to the board
        assert exc.code == 1
    assert len(created) == 1 and board_calls == [("cashbucket-com", "I_1")]


# ── codebase scan: the same block, wired the same way ───────────────────────────

def test_scan_file_issue_returns_the_created_json(scan, monkeypatch):
    monkeypatch.setattr(scan, "REPO", "infra-commons/legal")

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"number": 9, "node_id": "I_scan"}

    class _Client:
        def post(self, *a, **k):
            return _Resp()

    finding = {"severity": "HIGH", "location": "a.md:1", "category": "c", "description": "d"}
    existing: set = set()
    assert scan.file_issue(_Client(), finding, existing) == {"number": 9, "node_id": "I_scan"}
    assert scan.file_issue(_Client(), finding, existing) is None  # now a duplicate


def test_scan_main_files_every_finding_even_when_the_board_is_down(scan, monkeypatch, capsys):
    from types import SimpleNamespace

    findings = [
        {"severity": "HIGH", "location": "a.md:1", "category": "c", "description": "d1"},
        {"severity": "MEDIUM", "location": "b.md:2", "category": "c", "description": "d2"},
    ]
    msg = SimpleNamespace(stop_reason="end_turn")
    fake_ai = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: msg))
    filed, board_calls = [], []

    def fake_file_issue(client, finding, existing):
        filed.append(finding["location"])
        return {"number": len(filed), "node_id": f"I_{len(filed)}"}

    def failing_board(token, owner, node_id):
        board_calls.append((owner, node_id))
        return False, "could not read project #1 field map for 'klsjapan-com'"

    class _Http:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    for name, value in {
        "API_KEY": "k", "REPO": "klsjapan-com/legal",
        "collect_files": lambda: ["a.md"], "batch_files": lambda f: [f],
        "build_user_content": lambda b: "", "build_system_prompt": lambda: "",
        "anthropic": SimpleNamespace(Anthropic=lambda **k: fake_ai),
        "_response_text": lambda m: "", "parse_findings": lambda t: findings,
        "ensure_label": lambda c: None, "get_existing_titles": lambda c: set(),
        "file_issue": fake_file_issue, "add_to_board": failing_board,
    }.items():
        monkeypatch.setattr(scan, name, value)
    monkeypatch.setattr(scan.httpx, "Client", lambda **k: _Http())
    monkeypatch.setattr(scan.time, "sleep", lambda s: None)
    monkeypatch.setenv("BOARD_APP_TOKEN", "board-tok")
    monkeypatch.setenv("BOARD_KEY_FORWARDED", "true")

    scan.main()
    assert filed == ["a.md:1", "b.md:2"]
    assert board_calls == [("klsjapan-com", "I_1"), ("klsjapan-com", "I_2")]
    assert capsys.readouterr().out.count("::warning title=board intake::") == 2


# ── Drift guard: one board block, byte-identical in every filer ─────────────────

def _board_block(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    start = [i for i, ln in enumerate(lines) if ln.strip().startswith("# ── Board intake (Projects v2)")]
    end = [i for i, ln in enumerate(lines) if ln.strip().startswith("# ── End board intake")]
    assert len(start) == 1 and len(end) == 1, f"{path.name}: expected exactly one board block"
    return textwrap.dedent("\n".join(lines[start[0]:end[0] + 1]))


def test_scan_board_block_is_identical_to_capture():
    assert _board_block(SCAN_WORKFLOW) == _board_block(CAPTURE_WORKFLOW), (
        "the board-intake block has drifted between filers -- change it in one, copy it to all"
    )
