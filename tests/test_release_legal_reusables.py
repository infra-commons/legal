"""Tests for the legal-reusable release mechanism (infra-commons/legal#23).

Exercises the scripts directly (not via subprocess), against a real, throwaway git
repository -- these scripts are entirely about git tag/content state, so a real repo
catches what a mocked `subprocess.run` would happily paper over (e.g. a wrong git
invocation that mocks would never notice is wrong).
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "scripts"))

import check_legal_reusable_tags_released as tags_released  # noqa: E402
import check_legal_release_not_stuck as not_stuck  # noqa: E402
import release_legal_reusables as release  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────────

def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo with one reusable workflow, released at `sample/v1.0.0` + `sample/v1`.

    Has a real (local, bare) `origin` remote, so `git push` -- the operation the release
    mechanism's whole safety story rests on -- is actually exercised, not skipped.
    """
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    _git(root, "remote", "add", "origin", str(bare))

    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "sample-reusable.yml").write_text("name: sample v1\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "initial")
    _git(root, "branch", "-M", "main")  # independent of the box's init.defaultBranch
    _git(root, "tag", "sample/v1.0.0")
    _git(root, "tag", "sample/v1")
    _git(root, "push", "-q", "origin", "main", "sample/v1.0.0", "sample/v1")

    return root


# ── discover_families / content_hash ────────────────────────────────────────

def test_discover_families_finds_only_tagged_reusables(repo: Path):
    """A reusable with no moving tag (e.g. legal-capture-findings, SHA-pinned per #23) is invisible."""
    (repo / ".github" / "workflows" / "untagged-reusable.yml").write_text("name: untagged\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add untagged reusable")

    families = tags_released.discover_families(repo)

    assert families == {"sample": "sample/v1"}


def test_discover_families_empty_when_no_workflows_dir(tmp_path: Path):
    assert tags_released.discover_families(tmp_path) == {}


def test_content_hash_none_for_missing_path(repo: Path):
    assert tags_released.content_hash("HEAD", "no/such/file", repo) is None


def test_content_hash_matches_across_identical_tag(repo: Path):
    h_head = tags_released.content_hash("HEAD", ".github/workflows/sample-reusable.yml", repo)
    h_tag = tags_released.content_hash("sample/v1", ".github/workflows/sample-reusable.yml", repo)
    assert h_head == h_tag is not None


# ── evaluate (check_legal_reusable_tags_released) ───────────────────────────

def test_evaluate_fresh_when_head_matches_tag():
    stale, errors = tags_released.evaluate(
        {"sample": "sample/v1"}, {"sample": "abc"}, {"sample": "abc"}
    )
    assert stale == [] and errors == []


def test_evaluate_stale_when_head_differs_from_tag():
    stale, errors = tags_released.evaluate(
        {"sample": "sample/v1"}, {"sample": "abc"}, {"sample": "def"}
    )
    assert stale == ["sample"] and errors == []


def test_evaluate_errors_when_head_missing_the_file():
    stale, errors = tags_released.evaluate(
        {"sample": "sample/v1"}, {"sample": None}, {"sample": "def"}
    )
    assert stale == [] and len(errors) == 1
    assert "does not exist at HEAD" in errors[0]


def test_evaluate_errors_when_tag_missing_the_file():
    stale, errors = tags_released.evaluate(
        {"sample": "sample/v1"}, {"sample": "abc"}, {"sample": None}
    )
    assert stale == [] and len(errors) == 1
    assert "does not exist" in errors[0]


# ── release_legal_reusables: version numbering ──────────────────────────────

def test_next_version_starts_at_zero_with_no_prior_release(repo: Path):
    assert release.next_version("sample", "sample/v1", repo) == "sample/v1.1.0"


def test_next_version_increments_past_existing_releases(repo: Path):
    _git(repo, "tag", "sample/v1.1.0")
    _git(repo, "tag", "sample/v1.2.0")
    assert release.next_version("sample", "sample/v1", repo) == "sample/v1.3.0"


def test_next_version_is_scoped_to_the_major_line(repo: Path):
    """A v2 release line (if this family ever cuts one) doesn't see v1's history."""
    _git(repo, "tag", "sample/v1.5.0")
    assert release.next_version("sample", "sample/v2", repo) == "sample/v2.0.0"


# ── release_legal_reusables: end-to-end dry run + real run ──────────────────

def test_main_dry_run_reports_without_pushing(repo: Path, monkeypatch, capsys):
    (repo / ".github" / "workflows" / "sample-reusable.yml").write_text("name: sample v2\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "bump sample")

    monkeypatch.setenv("GITHUB_WORKSPACE", str(repo))
    monkeypatch.setenv("DRY_RUN", "true")
    rc = release.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "dry run" in out
    # The moving tag must NOT have advanced.
    assert _git(repo, "rev-parse", "sample/v1") != _git(repo, "rev-parse", "HEAD")


def test_main_no_op_when_nothing_changed(repo: Path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_WORKSPACE", str(repo))
    monkeypatch.delenv("DRY_RUN", raising=False)
    rc = release.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "nothing to do" in out


def test_main_refuses_to_run_with_zero_families(tmp_path: Path, monkeypatch, capsys):
    root = tmp_path / "empty"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    (root / "README.md").write_text("nothing here\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "initial")

    monkeypatch.setenv("GITHUB_WORKSPACE", str(root))
    rc = release.main()
    err = capsys.readouterr().out

    assert rc == 1
    assert "Refusing to run" in err


def test_main_moves_the_tag_and_cuts_an_immutable_release(repo: Path, monkeypatch, capsys):
    """End-to-end against a real (local, bare) remote: both tags land, and re-reading them
    from that remote (not from the local repo's own refs) confirms the push actually
    delivered -- the same "content, not refs, from the remote" property the script's own
    verification step relies on.
    """
    (repo / ".github" / "workflows" / "sample-reusable.yml").write_text("name: sample v2\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "bump sample")
    head = _git(repo, "rev-parse", "HEAD")

    monkeypatch.setenv("GITHUB_WORKSPACE", str(repo))
    monkeypatch.delenv("DRY_RUN", raising=False)
    rc = release.main()
    out = capsys.readouterr().out

    assert rc == 0
    assert "sample -> sample/v1.1.0" in out
    assert _git(repo, "rev-parse", "sample/v1") == head
    assert _git(repo, "rev-parse", "sample/v1.1.0") == head

    # And independently, from the "remote" -- a fresh clone sees the same state.
    clone = repo.parent / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(repo.parent / "origin.git"), str(clone)], check=True
    )
    assert _git(clone, "rev-parse", "sample/v1") == head
    assert _git(clone, "rev-parse", "sample/v1.1.0") == head


# ── check_legal_release_not_stuck: evaluate ─────────────────────────────────

def _run(status: str, created_at: str, run_id: int = 1) -> dict:
    return {"id": run_id, "status": status, "created_at": created_at, "html_url": "https://x"}


def test_not_stuck_errors_on_empty_run_list():
    stuck, messages = not_stuck.evaluate([], datetime.now(timezone.utc))
    assert stuck == []
    assert any(m.startswith("::error::") and "no" in m.lower() for m in messages)


def test_not_stuck_passes_for_a_recent_waiting_run():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stuck, messages = not_stuck.evaluate([_run("waiting", recent)], now)
    assert stuck == []
    assert not any(m.startswith("::error::") for m in messages)


def test_not_stuck_flags_a_run_held_past_the_threshold():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stuck, messages = not_stuck.evaluate([_run("waiting", old)], now)
    assert len(stuck) == 1
    assert any(m.startswith("::error::") and "legal-release" in m for m in messages)


def test_not_stuck_ignores_completed_runs():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stuck, messages = not_stuck.evaluate([_run("completed", old)], now)
    assert stuck == []
    assert not any(m.startswith("::error::") for m in messages)
