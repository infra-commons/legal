#!/usr/bin/env python3
"""Fail when a legal reusable's moving tag is behind the code on this branch.

Why this exists
----------------
`infra-commons/legal` ships some reusable workflows via a moving `<family>/v1` tag
(currently only `legal-review`, per infra-commons/legal#23's delivery-contract decision —
the other four reusables stay SHA-pinned per caller and are not this script's concern at
all, since they carry no moving tag for `discover_families()` to find). A caller that pins
`legal-review/v1` is supposed to get every fix on the next run after `release-legal-review.yml`
moves it. Nothing before this checked that the move actually happened.

Ported from `infra-commons/security/.github/scripts/check_composite_tags_released.py`,
simplified: legal has no `.github/actions/` directory, so a family's shipped surface here is
just its `.github/workflows/<family>-reusable.yml` file — there is no composite-action half
to compare alongside it.

What it asserts
----------------
For every family this repo releases at a `<family>/vN` moving tag, the content of its
reusable workflow file must be identical at that tag and at HEAD. Content hashes are
compared, not refs: a tag repointed to a different commit whose file content is identical is
correctly treated as released.

It is meaningful only on `main`. A pull request that changes a reusable *must* be behind its
tag until it merges — moving a tag onto a pre-merge commit is the hazard
infra-commons/security#59 recorded, so running this on a PR would demand the one thing that
must not happen.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

WORKFLOWS_DIR = ".github/workflows"
REUSABLE_SUFFIX = "-reusable.yml"

# Only moving major tags are our release mechanism. A raw SHA pin or `@main` is somebody
# deliberately opting out (or not yet opted in), and is not this check's business.
_MOVING_TAG_RE = re.compile(r"^[A-Za-z0-9._-]+/v\d+$")


def git(*args: str, cwd: Path, quiet: bool = False) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        if not quiet:
            detail = (exc.stderr or exc.stdout or "").strip().replace("\n", " | ")
            print(
                f"::error::git {' '.join(args)} failed (exit {exc.returncode}): "
                f"{detail[:300] or '(no output captured)'}"
            )
        raise


def reusable_path(family: str) -> str:
    return f"{WORKFLOWS_DIR}/{family}{REUSABLE_SUFFIX}"


def moving_tag_for(family: str, root: Path) -> str | None:
    """The family's moving tag, read from the tags that actually exist.

    This is how a family becomes visible at all: nothing in the repo names the moving tag
    outside a header comment, and a delivery contract living only in a comment isn't one
    this can rely on.
    """
    try:
        out = git("tag", "--list", f"{family}/v*", cwd=root, quiet=True)
    except subprocess.CalledProcessError:
        return None
    moving = sorted(t.strip() for t in out.splitlines() if _MOVING_TAG_RE.match(t.strip()))
    return moving[-1] if moving else None


def discover_families(root: Path) -> dict[str, str]:
    """Every family this repo releases -> its moving tag.

    A family is any `.github/workflows/<name>-reusable.yml` that already carries a moving
    `<name>/vN` tag. Deliberately not hardcoded to `legal-review`: a future second tag
    (infra-commons/legal#24, decided separately from #23) needs no code change here, only a
    tag to exist.
    """
    families: dict[str, str] = {}
    workflows = root / WORKFLOWS_DIR
    if not workflows.is_dir():
        return families
    for path in sorted(workflows.glob(f"*{REUSABLE_SUFFIX}")):
        family = path.name[: -len(REUSABLE_SUFFIX)]
        tag = moving_tag_for(family, root)
        if tag:
            families[family] = tag
    return families


def content_hash(ref: str, path: str, root: Path) -> str | None:
    """Blob hash of `path` at `ref`, or None if it does not exist there."""
    try:
        return git("rev-parse", f"{ref}:{path}", cwd=root, quiet=True)
    except subprocess.CalledProcessError:
        return None


def evaluate(pins: dict[str, str], head_hashes: dict[str, str | None], tag_hashes: dict[str, str | None]):
    """Pure decision step, so every failure mode is unit-testable.

    `head_hashes` / `tag_hashes` map family -> content hash at HEAD / at its tag (or None if
    the reusable file doesn't exist there). Returns (stale, errors).
    """
    stale: list[str] = []
    errors: list[str] = []

    for family, tag in sorted(pins.items()):
        head = head_hashes.get(family)
        tagged = tag_hashes.get(family)

        if head is None:
            errors.append(
                f"{family}: released at `{tag}` but {reusable_path(family)} does not exist "
                f"at HEAD."
            )
            continue
        if tagged is None:
            errors.append(
                f"{family}: tag `{tag}` does not exist, or {reusable_path(family)} does not "
                f"exist at that tag. Every consumer of this pin is broken until it does."
            )
            continue
        if head != tagged:
            stale.append(family)

    return stale, errors


def main() -> int:
    root = Path(
        os.environ.get("GITHUB_WORKSPACE")
        or git("rev-parse", "--show-toplevel", cwd=Path.cwd())
    )

    pins = discover_families(root)
    if not pins:
        # No releasable family is itself unremarkable *today* (legal-review is the only one
        # infra-commons/legal#23 decided to tag) -- but finding none because discovery broke
        # would look identical, so this stays a hard failure rather than a quiet pass.
        print(
            "::error::Found no releasable legal reusable(s) to check. This check reads "
            "`.github/workflows/*-reusable.yml` files carrying a moving `<family>/vN` tag; "
            "if the release mechanism changed, update or delete this check deliberately."
        )
        return 1

    head_hashes = {f: content_hash("HEAD", reusable_path(f), root) for f in pins}
    tag_hashes = {f: content_hash(pins[f], reusable_path(f), root) for f in pins}

    stale, errors = evaluate(pins, head_hashes, tag_hashes)

    for family in stale:
        print(
            f"::error::`{family}` is unreleased: {reusable_path(family)} on this branch "
            f"differs from the content at `{pins[family]}`, so every consumer is still "
            f"running the old version. release-legal-review.yml should have moved this tag; "
            f"check whether it ran (and whether it's waiting on `legal-release` approval)."
        )
    for line in errors:
        print(f"::error::{line}")

    if stale or errors:
        print(
            f"\n{len(stale)} unreleased legal reusable(s), {len(errors)} error(s). "
            f"Moving the tag is the release; merging is not."
        )
        return 1

    print(f"All {len(pins)} legal reusable moving tag(s) match the code on this branch. ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
