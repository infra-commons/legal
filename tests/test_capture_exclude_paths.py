"""The capture reusable's reviewed-diff exclusions: one hardcoded, the rest the caller's choice.

infra-commons/legal#31 ask 2: get_diff() hardcoded one exclusion (the suppression files). An
`exclude_paths` input now appends caller globs to it. Unset, the git argv is byte-identical.
The trade is the caller's: an excluded release note can also be where a live residual exposure
is first written down, so nothing is excluded beyond the suppression files unless asked.
"""
from __future__ import annotations

import subprocess

import pytest
import yaml

from conftest import CAPTURE_WORKFLOW

A, B = ("a" * 40, "b" * 40)
TODAY_ARGV = ["git", "diff", f"{A}...{B}", "--", ".", ":(exclude,glob).github/*-suppressions.yml"]


# ── parse_exclude_paths ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("", []),
    ("   ", []),
    ("docs/release-notes/**", ["docs/release-notes/**"]),
    (" a/** , b/*.md ,, ", ["a/**", "b/*.md"]),
    ("a/**\nb/*.md\n", ["a/**", "b/*.md"]),
])
def test_parse_exclude_paths(capture, raw, expected):
    assert capture.parse_exclude_paths(raw) == expected


def test_pathspec_magic_entry_is_rejected(capture):
    with pytest.raises(ValueError, match="exclude_paths"):
        capture.parse_exclude_paths("docs/**,:(top)src")


# ── get_diff argv ────────────────────────────────────────────────────────────

def _record_argv(capture, monkeypatch):
    seen = []

    def fake_run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(capture.subprocess, "run", fake_run)
    return seen


def test_default_argv_is_unchanged(capture, monkeypatch):
    seen = _record_argv(capture, monkeypatch)
    capture.get_diff(A, B)
    assert seen == [TODAY_ARGV]


def test_caller_globs_append_after_the_hardcoded_exclusion(capture, monkeypatch):
    seen = _record_argv(capture, monkeypatch)
    capture.get_diff(A, B, ["docs/release-notes/**", "CHANGELOG.md"])
    assert seen == [TODAY_ARGV + [":(exclude,glob)docs/release-notes/**",
                                  ":(exclude,glob)CHANGELOG.md"]]


# ── real git: what the reviewer actually sees ────────────────────────────────

def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "seed").write_text("x\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "seed")
    base = _git(tmp_path, "rev-parse", "HEAD")
    for rel in ("docs/release-notes/v2.md", "docs/guide.md", "src/a.py",
                ".github/legal-review-suppressions.yml"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(f"{rel}\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "change")
    monkeypatch.chdir(tmp_path)
    return base, _git(tmp_path, "rev-parse", "HEAD")


def _files(diff):
    return sorted(line.split(" b/", 1)[1] for line in diff.splitlines()
                  if line.startswith("diff --git "))


def test_default_excludes_only_the_suppression_files(capture, repo):
    assert _files(capture.get_diff(*repo)) == [
        "docs/guide.md", "docs/release-notes/v2.md", "src/a.py"]


def test_caller_glob_drops_its_paths_and_keeps_the_hardcoded_one(capture, repo):
    assert _files(capture.get_diff(*repo, ["docs/release-notes/**"])) == [
        "docs/guide.md", "src/a.py"]


def test_excluded_by_caller_names_what_the_globs_dropped(capture, repo):
    assert capture.excluded_by_caller(*repo, ["docs/**"]) == [
        "docs/guide.md", "docs/release-notes/v2.md"]


# ── main(): exit codes and the log a caller reads ────────────────────────────

def _main_env(monkeypatch, **kw):
    env = {"ANTHROPIC_API_KEY": "k", "GITHUB_TOKEN": "t", "REPO": "infra-commons/legal",
           "BEFORE_SHA": A, "AFTER_SHA": B, "BASE_SHA_INPUT": "", "HEAD_SHA_INPUT": "",
           "EXCLUDE_PATHS_INPUT": "", "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/main"}
    env.update(kw)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_main_bad_entry_exits_1_before_any_diff(capture, monkeypatch, capsys):
    _main_env(monkeypatch, EXCLUDE_PATHS_INPUT=":(top)x")

    def must_not_run(*a, **k):
        raise AssertionError("a bad exclude_paths entry must stop the run before any diff")

    monkeypatch.setattr(capture, "get_diff", must_not_run)
    with pytest.raises(SystemExit) as exc:
        capture.main()
    assert exc.value.code == 1
    assert "exclude_paths" in capsys.readouterr().err


def test_main_logs_what_the_caller_globs_dropped(capture, monkeypatch, capsys):
    _main_env(monkeypatch, EXCLUDE_PATHS_INPUT="docs/**")
    seen = []
    monkeypatch.setattr(capture, "get_diff", lambda b, a, ex=(): seen.append(ex) or "")
    monkeypatch.setattr(capture, "excluded_by_caller", lambda b, a, ex: ["docs/x.md"])
    capture.main()  # everything excluded -> empty diff -> clean return, but said so
    out = capsys.readouterr().out
    assert seen == [["docs/**"]]
    assert "dropped 1 changed file(s) from review" in out and "docs/x.md" in out


# ── the wiring: default leaves existing callers untouched ────────────────────

def _workflow():
    return yaml.safe_load(CAPTURE_WORKFLOW.read_text(encoding="utf-8"))


def test_exclude_paths_input_is_optional_and_defaults_empty():
    spec = _workflow()[True]["workflow_call"]["inputs"]["exclude_paths"]
    assert (spec["required"], spec["default"], spec["type"]) == (False, "", "string")


def test_step_env_routes_the_input_through_env():
    steps = _workflow()["jobs"]["capture"]["steps"]
    env = next(s for s in steps if s.get("name") == "Capture legal findings from the merged diff")["env"]
    assert env["EXCLUDE_PATHS_INPUT"] == "${{ inputs.exclude_paths }}"
