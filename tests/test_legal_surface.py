"""Properties of the legal-review path filter.

The filter decides whether a PR gets an (expensive, merge-gating) legal review
at all, so the invariant that matters is directional: it may review too much,
never too little. Every property below is written to catch a weakening.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# Profiles are registered and loaded in conftest.py.


# ── strategies ────────────────────────────────────────────────────────────────

def _tokens(reviewer):
    return list(reviewer.LEGAL_SURFACE_TOKENS)


# Path text that provably contains none of the tokens. Built from a restricted
# alphabet and filtered, so "no token present" is guaranteed rather than assumed.
clean_text = st.text(alphabet="qwxzjkv0123456789-_/", min_size=1, max_size=40)

path_lists = st.lists(st.text(min_size=0, max_size=60), max_size=8)


def near_misses(token: str) -> st.SearchStrategy[str]:
    """Strings one edit away from a token -- the inputs st.text() never invents.

    Without this a mutation that loosens the match (e.g. comparing only a
    prefix of the token) passes every generated example, because random text
    essentially never lands near a specific magic string.
    """
    drops = [token[:i] + token[i + 1 :] for i in range(len(token))]
    swaps = [token[:i] + "é" + token[i + 1 :] for i in range(len(token))]
    prefixes = [token[: i + 1] for i in range(len(token) - 1)]
    return st.sampled_from([s for s in drops + swaps + prefixes if s])


# ── totality & fail-closed ────────────────────────────────────────────────────

@given(paths=path_lists)
@settings(max_examples=200)
def test_is_total_and_returns_bool(reviewer, paths):
    """Never raises and always returns a real bool, whatever the paths look like."""
    assert isinstance(reviewer.touches_legal_surface(paths), bool)


def test_empty_path_list_reviews_anyway(reviewer):
    """Unknown changed-file list must fail CLOSED -- review, don't skip."""
    assert reviewer.touches_legal_surface([]) is True


# ── the core matching contract ────────────────────────────────────────────────

@given(data=st.data(), prefix=clean_text, suffix=clean_text)
@settings(max_examples=300)
def test_token_matches_anywhere_in_the_path(reviewer, data, prefix, suffix):
    """A token counts ANYWHERE in the path -- never anchored to start or end.

    Anchoring is the tempting "tidy-up" that would silently stop reviewing
    e.g. `src/app/privacy/notice.ts`, so it gets its own property.
    """
    token = data.draw(st.sampled_from(_tokens(reviewer)))
    assert reviewer.touches_legal_surface([f"{prefix}{token}{suffix}"]) is True


@given(data=st.data())
@settings(max_examples=200)
def test_matching_is_case_insensitive(reviewer, data):
    token = data.draw(st.sampled_from(_tokens(reviewer)))
    mangled = data.draw(st.sampled_from([token.upper(), token.capitalize(), token.swapcase()]))
    assert reviewer.touches_legal_surface([f"docs/{mangled}/notes.md"]) is True


@given(paths=st.lists(clean_text, min_size=1, max_size=6))
@settings(max_examples=300)
def test_token_free_paths_are_skipped(reviewer, paths):
    """Only the declared tokens may trigger a review."""
    assume(not reviewer.touches_legal_surface(paths))  # sanity: alphabet is clean
    assert reviewer.touches_legal_surface(paths) is False


@given(data=st.data())
@settings(max_examples=300)
def test_near_misses_do_not_match(reviewer, data):
    """A string ALMOST a token must not trigger -- catches loosened comparisons."""
    token = data.draw(st.sampled_from(_tokens(reviewer)))
    candidate = data.draw(near_misses(token))
    # Only meaningful if the near-miss genuinely contains no token.
    assume(not any(t in candidate.lower() for t in _tokens(reviewer)))
    assert reviewer.touches_legal_surface([candidate]) is False


# ── monotonicity ──────────────────────────────────────────────────────────────

nonblank_lists = st.lists(
    st.text(min_size=1, max_size=60).filter(lambda s: s.strip()),
    min_size=1, max_size=8,
)


@given(a=nonblank_lists, b=nonblank_lists)
@settings(max_examples=300)
def test_monotone_under_union(reviewer, a, b):
    """Adding files can only ever turn skip -> review, never review -> skip.

    This is the property that makes the filter safe under `synchronize`: pushing
    another commit to a PR can never downgrade it out of legal review. It is not
    expressible as an example-based test.

    Stated over non-empty lists on purpose: the empty list is the fail-closed
    "we don't know what changed" sentinel, which is deliberately the MAXIMUM of
    the order, so union with it cannot be monotone and must not be conflated
    with "nothing legal changed".
    """
    if reviewer.touches_legal_surface(a) or reviewer.touches_legal_surface(b):
        assert reviewer.touches_legal_surface(a + b) is True


@given(blanks=st.lists(st.sampled_from(["", " ", "\t", "\n"]), min_size=1, max_size=4))
@settings(max_examples=50)
def test_all_blank_paths_are_treated_as_unknown(reviewer, blanks):
    """[""] must not be a third state -- it means "unknown", same as []."""
    assert reviewer.touches_legal_surface(blanks) is True


# ── worked examples (readable intent) ─────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "policies/privacy-policy.md",
    "docs/terms-of-service.md",
    "src/legal/consent.ts",
    "content/articles/2026-launch.md",
    "db/migrations/0008_macro_targets.sql",
    "schema/contracts.schema.json",
    "marketing/copy/landing.md",
    "infra/data-retention.bicep",
])
def test_real_legal_surfaces_are_reviewed(reviewer, path):
    assert reviewer.touches_legal_surface([path]) is True


@pytest.mark.parametrize("path", [
    ".github/workflows/ci.yml",
    "src/utils/translate.py",       # contains "sla" -- must NOT match
    "src/lib/standard.ts",          # contains "nda" -- must NOT match
    "assets/photos/hero.png",       # contains "tos" -- must NOT match
    "src/routes/mapping.ts",        # contains "appi" -- must NOT match
    "Makefile",
])
def test_pure_code_paths_are_skipped(reviewer, path):
    assert reviewer.touches_legal_surface([path]) is False


# ── the untruncated-listing guarantee ─────────────────────────────────────────

def test_get_changed_files_rejects_non_sha(reviewer):
    with pytest.raises(ValueError):
        reviewer.get_changed_files("HEAD", "main")


def test_get_changed_files_lists_every_file_on_a_big_diff(reviewer, tmp_path, monkeypatch):
    """The listing must not truncate -- that is the whole reason it is a
    separate `--name-only` diff rather than a parse of the truncated review diff."""
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(a, cwd=repo, check=True, capture_output=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "seed")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True, check=True).stdout.strip()

    # Enough content that the reviewer's own diff would be truncated.
    filler = "x" * 4000
    names = [f"code_{i:03d}.py" for i in range(40)] + ["policies/privacy.md"]
    (repo / "policies").mkdir()
    for n in names:
        (repo / n).write_text(filler + "\n")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "big")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True, check=True).stdout.strip()

    monkeypatch.chdir(repo)
    changed = reviewer.get_changed_files(base, head)

    assert sorted(changed) == sorted(names)
    # The legal file is last alphabetically-ish and would be the one lost to a
    # truncating implementation -- its presence is what keeps the filter honest.
    assert "policies/privacy.md" in changed
    assert reviewer.touches_legal_surface(changed) is True
