#!/usr/bin/env python3
"""Release every legal reusable whose moving tag is behind `main`.

Ported from `infra-commons/security/.github/scripts/release_composites.py`, simplified for
this repo's surface: no `.github/actions/` directory exists here, so a family's shipped
surface is just its `.github/workflows/<family>-reusable.yml` file.

For each family whose reusable workflow file at HEAD differs from the file at its
`<family>/vN` moving tag, this:

  1. cuts an immutable `<family>/vN.M.0` release tag at HEAD, so every release stays
     individually addressable and a bad one can be pinned away from; then
  2. moves `<family>/vN` to HEAD.

Safety properties, in the order they matter:

* **Post-merge only.** It runs on `push` to `main` (via the calling workflow's
  `workflow_run` trigger), so HEAD is always a merged commit. Moving a tag onto a pre-merge
  commit is the infra-commons/security#59 hazard and is structurally impossible here; there
  is no input by which a caller can point it at a branch.
* **Tests first.** The calling workflow gates this on `Tests` passing. `legal-review / gate`
  is a required check on multiple caller repos with no per-caller pin bump to review it, so
  the tests are the only automated check between an edit here and the fleet.
* **Content, not refs.** Staleness is decided by comparing the git blob hash of the reusable
  file, so a tag already pointing at equivalent content is left alone and the job is a no-op
  on the overwhelming majority of pushes.
* **Idempotent.** Re-running on an unchanged `main` releases nothing.
* **Forward-only.** The moving tag is never moved onto a commit the tag is already ahead
  of. This job checks out `workflow_run.head_sha`, and more than one run can sit on the
  `legal-release` gate at once with no imposed approval order -- so a stale run must not
  un-release a newer one. Ancestry decides ORDER only; it says nothing about whether the
  newer release was good.
* **App-authenticated push.** The calling workflow checks out with a token minted for the
  `infra-commons-bot` App — the only identity `protect-moving-tags` lets move `*/v1` here
  (unlike infra-commons/security, whose ruleset permits `GITHUB_TOKEN`; see
  `release-legal-review.yml`'s header comment for why that differs).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_legal_reusable_tags_released import (  # noqa: E402
    discover_families,
    content_hash,
    git,
    is_ancestor,
    reusable_path,
)

_VERSION_TAG_RE = re.compile(r"^(?P<family>[A-Za-z0-9._-]+)/v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")


def existing_versions(family: str, major: int, root: Path) -> list[tuple[int, int]]:
    """(minor, patch) pairs already released for this family's major line."""
    out = git("tag", "--list", f"{family}/v{major}.*", cwd=root)
    versions = []
    for line in out.splitlines():
        match = _VERSION_TAG_RE.match(line.strip())
        if match and match.group("family") == family and int(match.group("major")) == major:
            versions.append((int(match.group("minor")), int(match.group("patch"))))
    return sorted(versions)


def next_version(family: str, moving_tag: str, root: Path) -> str:
    """The next minor release on this family's major line."""
    major = int(moving_tag.rsplit("/v", 1)[1])
    versions = existing_versions(family, major, root)
    next_minor = (versions[-1][0] + 1) if versions else 0
    return f"{family}/v{major}.{next_minor}.0"


def main() -> int:
    root = Path(
        os.environ.get("GITHUB_WORKSPACE")
        or git("rev-parse", "--show-toplevel", cwd=Path.cwd())
    )
    dry_run = os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}

    head = git("rev-parse", "HEAD", cwd=root)
    pins = discover_families(root)
    if not pins:
        print(
            "::error::Found no releasable legal reusable(s). Refusing to run: a release job "
            "that silently releases nothing is worse than one that fails."
        )
        return 1

    released: list[str] = []
    for family, moving_tag in sorted(pins.items()):
        path = reusable_path(family)
        head_hash = content_hash("HEAD", path, root)
        tag_hash = content_hash(moving_tag, path, root)

        if head_hash is None:
            print(f"::error::{family}: released at `{moving_tag}` but {path} does not exist at HEAD")
            return 1
        if head_hash == tag_hash:
            print(f"{family}: already released at `{moving_tag}`, nothing to do")
            continue

        # Ancestry establishes ORDER, never correctness -- and order is the thing this job
        # cannot otherwise know. It checks out `workflow_run.head_sha`, not `main`, and more
        # than one run can sit on the `legal-release` gate at once (runs 25/26 did, pinned to
        # different commits; 10/19 did for days). The environment imposes no approval order,
        # so approving the newer run first would leave the older one force-moving the moving
        # tag BACKWARD onto its own stale commit -- un-releasing merged code to every caller
        # and passing its own post-move verify, which compares the tag against that same
        # stale HEAD. The tag is known to exist here: `discover_families` found it.
        tag_commit = git("rev-parse", f"{moving_tag}^{{commit}}", cwd=root)
        if not is_ancestor(moving_tag, "HEAD", root):
            if is_ancestor("HEAD", moving_tag, root):
                # Says only that a later commit is tagged, which is all ancestry can show.
                # Deliberately claims nothing about whether that release was any good.
                print(
                    f"{family}: `{moving_tag}` is at {tag_commit[:12]}, a descendant of this "
                    f"run's {head[:12]}. Superseded by a newer release; nothing to release "
                    f"here. Not moving the tag backward."
                )
                continue
            print(
                f"::error::{family}: refusing to move `{moving_tag}`. The tag is at "
                f"{tag_commit[:12]}, which is neither an ancestor nor a descendant of this "
                f"run's {head[:12]}, so the direction of the move cannot be established. "
                f"Histories diverged (a force-push to `main`, or a tag pointed at an "
                f"unrelated commit); resolve that deliberately rather than letting a release "
                f"guess."
            )
            return 1

        version_tag = next_version(family, moving_tag, root)
        state = "does not exist yet" if tag_hash is None else "is behind"
        print(f"{family}: `{moving_tag}` {state}, releasing {version_tag} at {head[:12]}")

        if dry_run:
            released.append(f"{family} -> {version_tag} (dry run)")
            continue

        # The immutable release tag is created, never forced. `protect-immutable-tags` has
        # no bypass actor at all, so an attempt to move one is rejected by the server; failing
        # loudly on a local collision is the same answer, sooner.
        git("tag", version_tag, head, cwd=root)
        git("push", "origin", version_tag, cwd=root)

        # The moving tag is a force by definition. `protect-moving-tags` permits this only
        # for the App whose token this job's checkout was authenticated with.
        git("tag", "-f", moving_tag, head, cwd=root)
        git("push", "-f", "origin", moving_tag, cwd=root)

        # Verify by content, from the remote, not from what we just pushed locally.
        git("fetch", "--force", "origin", f"refs/tags/{moving_tag}:refs/tags/{moving_tag}", cwd=root)
        landed = content_hash(moving_tag, path, root)
        if landed != head_hash:
            print(
                f"::error::{family}: pushed `{moving_tag}` but the remote tag still resolves "
                f"to different content. The release did not land."
            )
            return 1

        released.append(f"{family} -> {version_tag}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if released:
        lines = ["### Legal reusables released", ""] + [f"- `{line}`" for line in released]
    else:
        lines = ["### Legal reusables released", "", "None. Every moving tag already matched `main`."]
    print("\n".join(lines))
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
