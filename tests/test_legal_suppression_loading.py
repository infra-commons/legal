"""Properties of suppression *loading*: expiry, and where the repo-local file is read from.

Both failures here are silent by construction:

  a suppression that never expires   keeps hiding a finding long after the
                                     accepted-risk window closed, and nothing
                                     anywhere says the window closed
  a suppression read from the PR     lets the change under review decide what the
  working tree                       review is allowed to say about it

The second is the one with teeth, so it is tested against a real git repository
rather than a mock: the assertion that matters is that a file present ONLY in the
working tree does not load, and a mock of `git show` would be asserting my own
mental model rather than git's behaviour.
"""
from __future__ import annotations

import os
import subprocess
from datetime import date, timedelta

import pytest
import yaml

SUPPRESSIONS_PATH = ".github/legal-review-suppressions.yml"


def _iso(days_from_today: int) -> str:
    return (date.today() + timedelta(days=days_from_today)).isoformat()


# ── item 3: expiry ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("module", ["reviewer", "capture"])
def test_an_expired_suppression_is_dropped(module, request):
    mod = request.getfixturevalue(module)
    entries = [{"id": "lapsed", "file_pattern": ".*", "expires": _iso(-1)}]
    assert mod.drop_expired(entries) == []


@pytest.mark.parametrize("module", ["reviewer", "capture"])
def test_a_future_suppression_is_kept(module, request):
    mod = request.getfixturevalue(module)
    entries = [{"id": "live", "file_pattern": ".*", "expires": _iso(90)}]
    assert mod.drop_expired(entries) == entries


@pytest.mark.parametrize("module", ["reviewer", "capture"])
def test_an_entry_with_no_expires_is_permanent(module, request):
    """Absent `expires` must keep working — most existing entries have none, and
    expiring them all would un-suppress the entire fleet at once."""
    mod = request.getfixturevalue(module)
    entries = [{"id": "forever", "file_pattern": ".*"}]
    assert mod.drop_expired(entries) == entries


@pytest.mark.parametrize("module", ["reviewer", "capture"])
def test_an_entry_expiring_today_is_still_live(module, request):
    """Boundary. `days_left == 0` is the last day it applies, not the first day
    it does not."""
    mod = request.getfixturevalue(module)
    entries = [{"id": "today", "file_pattern": ".*", "expires": _iso(0)}]
    assert mod.drop_expired(entries) == entries


@pytest.mark.parametrize("module", ["reviewer", "capture"])
def test_an_unparseable_date_is_treated_as_no_expiry_and_warned(module, request, capsys):
    """Deliberately the safe direction: treating a typo as 'expired' would
    silently un-suppress an accepted finding, which reads as a new finding
    appearing from nowhere. Ported from adversarial-review.py."""
    mod = request.getfixturevalue(module)
    entries = [{"id": "typo", "file_pattern": ".*", "expires": "2026-13-45"}]
    assert mod.drop_expired(entries) == entries
    assert "unparseable" in capsys.readouterr().err


@pytest.mark.parametrize("module", ["reviewer", "capture"])
def test_an_entry_expiring_soon_is_kept_but_warned(module, request, capsys):
    mod = request.getfixturevalue(module)
    entries = [{"id": "soon", "file_pattern": ".*", "expires": _iso(5)}]
    assert mod.drop_expired(entries) == entries
    assert "expires in" in capsys.readouterr().err


@pytest.mark.parametrize("module", ["reviewer", "capture"])
def test_expiry_does_not_drop_the_whole_list(module, request):
    """A live entry beside an expired one must survive — the failure that would
    turn expiry into a silent 'suppress nothing'."""
    mod = request.getfixturevalue(module)
    live = {"id": "live", "file_pattern": ".*", "expires": _iso(30)}
    dead = {"id": "dead", "file_pattern": ".*", "expires": _iso(-30)}
    assert mod.drop_expired([dead, live]) == [live]


# ── item 4: the repo-local file comes from the BASE commit ────────────────────


@pytest.fixture
def repo_with_base(tmp_path, monkeypatch):
    """A real git repo: one commit as the PR base, plus a dirty working tree.

    Returns (base_sha, write_working_tree_file). The working tree is left dirty
    on purpose — that is exactly the state a `pull_request` checkout is in.
    """
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True,
                              capture_output=True, text=True).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "README.md").write_text("base\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    base_sha = git("rev-parse", "HEAD")

    def write_working_tree_file(content: str):
        path = tmp_path / SUPPRESSIONS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BASE_SHA", base_sha)
    return base_sha, write_working_tree_file, git


def test_a_suppression_added_only_by_the_pr_does_not_take_effect(reviewer, repo_with_base):
    """THE test for this item. The file exists in the working tree (the PR's own
    head) and not at the base commit, so it must not load. Otherwise a PR can add
    a suppression and have it apply to itself."""
    _, write_wt, _ = repo_with_base
    write_wt(yaml.safe_dump({"suppressions": [
        {"id": "self-granted", "file_pattern": ".*", "finding_pattern": ".*"}
    ]}))
    assert (tmp := os.path.isfile(SUPPRESSIONS_PATH)) is True, "fixture must leave the file present"
    assert reviewer._read_local_suppressions_from_base() == []


def test_a_suppression_committed_on_the_base_does_take_effect(reviewer, repo_with_base):
    """The other direction — the mechanism must still work, or this becomes a
    filter that never matches."""
    _, write_wt, git = repo_with_base
    write_wt(yaml.safe_dump({"suppressions": [{"id": "accepted", "file_pattern": "^vendor/"}]}))
    git("add", "-A")
    git("commit", "-qm", "add suppressions")
    new_base = git("rev-parse", "HEAD")
    os.environ["BASE_SHA"] = new_base

    entries = reviewer._read_local_suppressions_from_base()
    assert [e["id"] for e in entries] == ["accepted"]


def test_a_pr_edit_to_an_existing_entry_uses_the_base_version(reviewer, repo_with_base):
    """The subtler half: the file exists on base, and the PR widens it. The base
    version must win, or a PR can broaden its own suppression."""
    _, write_wt, git = repo_with_base
    write_wt(yaml.safe_dump({"suppressions": [{"id": "narrow", "file_pattern": "^vendor/"}]}))
    git("add", "-A")
    git("commit", "-qm", "narrow rule")
    os.environ["BASE_SHA"] = git("rev-parse", "HEAD")

    write_wt(yaml.safe_dump({"suppressions": [{"id": "narrow", "file_pattern": ".*"}]}))
    entries = reviewer._read_local_suppressions_from_base()
    assert entries == [{"id": "narrow", "file_pattern": "^vendor/"}]


def test_an_absent_file_on_base_is_no_suppressions_not_an_error(reviewer, repo_with_base):
    assert reviewer._read_local_suppressions_from_base() == []


def test_a_non_sha_base_does_not_fall_back_to_the_working_tree(reviewer, repo_with_base, capsys):
    """Fail closed. If BASE_SHA is missing or malformed, loading nothing means
    'review everything'; falling back to the working tree would reopen the hole
    precisely when the environment is already wrong."""
    _, write_wt, _ = repo_with_base
    write_wt(yaml.safe_dump({"suppressions": [{"id": "x", "file_pattern": ".*"}]}))
    for bad in ("", "main", "origin/main", "../../etc/passwd", "HEAD; rm -rf /"):
        os.environ["BASE_SHA"] = bad
        assert reviewer._read_local_suppressions_from_base() == [], bad
    assert "not a commit sha" in capsys.readouterr().err


def test_unparseable_yaml_on_base_suppresses_nothing(reviewer, repo_with_base):
    """An unreadable suppressions file must mean 'no suppressions', never
    'suppress everything'."""
    _, write_wt, git = repo_with_base
    write_wt("suppressions: [ this is not: valid: yaml")
    git("add", "-A")
    git("commit", "-qm", "broken")
    os.environ["BASE_SHA"] = git("rev-parse", "HEAD")
    assert reviewer._read_local_suppressions_from_base() == []
