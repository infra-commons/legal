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


def test_board_add_severities_is_high_only(capture):
    # A deliberate, named scope decision (infra-commons/meta#661) — CRITICAL already blocks the
    # PR-time gate and MEDIUM/LOW never get an individual issue to add. Pin it with a test so a
    # future change to this set is a decision, not an accident.
    assert capture.BOARD_ADD_SEVERITIES == {"HIGH"}
