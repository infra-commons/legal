"""The capture reusable's reviewed range: caller-configurable, and never a silent green.

infra-commons/legal#31: the range came only from github.event.before/after. A tag push has an
all-zeros `before`, which took the branch-creation exit 0 -- green, and nothing reviewed. A
schedule / dispatch caller had no range at all and no way to supply one. `base_sha`/`head_sha`
inputs now override each side; unset, a push caller's range is exactly what it was.
"""
from __future__ import annotations

import pytest
import yaml

from conftest import CAPTURE_WORKFLOW

A, B, C, D = ("a" * 40, "b" * 40, "c" * 40, "d" * 40)
ZERO = "0" * 40


def _env(**kw):
    base = {"BEFORE_SHA": "", "AFTER_SHA": "", "BASE_SHA_INPUT": "", "HEAD_SHA_INPUT": "",
            "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main"}
    base.update(kw)
    return base


# ── resolve_range ────────────────────────────────────────────────────────────

def test_default_is_the_push_event_range_unchanged(capture):
    assert capture.resolve_range(_env(BEFORE_SHA=A, AFTER_SHA=B)) == (A, B)


def test_a_valid_push_range_ignores_event_and_ref(capture):
    env = _env(BEFORE_SHA=A, AFTER_SHA=B, GITHUB_EVENT_NAME="", GITHUB_REF="refs/tags/v1")
    assert capture.resolve_range(env) == (A, B)


@pytest.mark.parametrize("inputs, expected", [
    ({"BASE_SHA_INPUT": C, "HEAD_SHA_INPUT": D}, (C, D)),
    ({"BASE_SHA_INPUT": C}, (C, B)),
    ({"HEAD_SHA_INPUT": D}, (A, D)),
])
def test_inputs_override_each_side(capture, inputs, expected):
    assert capture.resolve_range(_env(BEFORE_SHA=A, AFTER_SHA=B, **inputs)) == expected


@pytest.mark.parametrize("bad", ["main", "v1.2.0", "a" * 39, "--output=x", ZERO])
def test_a_set_input_must_be_a_real_sha(capture, bad):
    with pytest.raises(ValueError, match="base_sha"):
        capture.resolve_range(_env(BEFORE_SHA=A, AFTER_SHA=B, BASE_SHA_INPUT=bad))


def test_tag_push_with_zero_before_fails_loud(capture):
    env = _env(BEFORE_SHA=ZERO, AFTER_SHA=B, GITHUB_REF="refs/tags/v1.2.0")
    with pytest.raises(ValueError, match="tag push.*base_sha"):
        capture.resolve_range(env)


def test_tag_push_with_base_input_reviews_the_given_range(capture):
    env = _env(BEFORE_SHA=ZERO, AFTER_SHA=B, BASE_SHA_INPUT=A, GITHUB_REF="refs/tags/v1.2.0")
    assert capture.resolve_range(env) == (A, B)


def test_branch_creation_still_exits_clean(capture, capsys):
    assert capture.resolve_range(_env(BEFORE_SHA=ZERO, AFTER_SHA=B)) is None
    assert "branch creation" in capsys.readouterr().out


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch", "release"])
def test_non_push_event_without_inputs_names_the_fix(capture, event):
    with pytest.raises(ValueError, match=f"'{event}'.*base_sha/head_sha"):
        capture.resolve_range(_env(GITHUB_EVENT_NAME=event, GITHUB_REF="refs/heads/main"))


def test_non_push_event_with_inputs_resolves(capture):
    env = _env(GITHUB_EVENT_NAME="schedule", BASE_SHA_INPUT=C, HEAD_SHA_INPUT=D)
    assert capture.resolve_range(env) == (C, D)


# ── main(): the exit code a caller actually sees ─────────────────────────────

def _main_env(capture, monkeypatch, **kw):
    for key, value in {"ANTHROPIC_API_KEY": "k", "GITHUB_TOKEN": "t",
                       "REPO": "infra-commons/legal", **_env(**kw)}.items():
        monkeypatch.setenv(key, value)

    def must_not_run(*a, **k):
        raise AssertionError("no range was resolvable, so nothing may be diffed or reviewed")

    monkeypatch.setattr(capture, "get_diff", must_not_run)
    monkeypatch.setattr(capture, "review_diff", must_not_run)


def test_main_tag_push_exits_1_before_any_review(capture, monkeypatch, capsys):
    _main_env(capture, monkeypatch, BEFORE_SHA=ZERO, AFTER_SHA=B, GITHUB_REF="refs/tags/v2")
    with pytest.raises(SystemExit) as exc:
        capture.main()
    assert exc.value.code == 1
    assert "tag push" in capsys.readouterr().err


def test_main_schedule_without_inputs_exits_1(capture, monkeypatch, capsys):
    _main_env(capture, monkeypatch, GITHUB_EVENT_NAME="schedule")
    with pytest.raises(SystemExit) as exc:
        capture.main()
    assert exc.value.code == 1
    assert "base_sha/head_sha" in capsys.readouterr().err


def test_main_branch_creation_returns_clean(capture, monkeypatch):
    _main_env(capture, monkeypatch, BEFORE_SHA=ZERO, AFTER_SHA=B)
    capture.main()  # no SystemExit


def test_main_diffs_the_input_range(capture, monkeypatch):
    _main_env(capture, monkeypatch, GITHUB_EVENT_NAME="schedule",
              BASE_SHA_INPUT=C, HEAD_SHA_INPUT=D)
    seen = []
    monkeypatch.setattr(capture, "get_diff", lambda b, a, *_: seen.append((b, a)) or "")
    capture.main()  # empty diff -> clean return
    assert seen == [(C, D)]


# ── the wiring: defaults leave existing callers untouched ────────────────────

def _workflow():
    return yaml.safe_load(CAPTURE_WORKFLOW.read_text(encoding="utf-8"))


def test_range_inputs_are_optional_and_default_empty():
    inputs = _workflow()[True]["workflow_call"]["inputs"]  # PyYAML reads `on:` as True
    for name in ("base_sha", "head_sha"):
        assert inputs[name]["required"] is False
        assert inputs[name]["default"] == ""
        assert inputs[name]["type"] == "string"


def test_step_env_keeps_the_event_range_and_routes_inputs_through_env():
    steps = _workflow()["jobs"]["capture"]["steps"]
    env = next(s for s in steps if s.get("name") == "Capture legal findings from the merged diff")["env"]
    assert env["BEFORE_SHA"] == "${{ github.event.before }}"
    assert env["AFTER_SHA"] == "${{ github.event.after }}"
    assert env["BASE_SHA_INPUT"] == "${{ inputs.base_sha }}"
    assert env["HEAD_SHA_INPUT"] == "${{ inputs.head_sha }}"
