#!/usr/bin/env python3
"""Fail when a release run has been waiting on its approval gate for too long.

Ported near-verbatim from
`infra-commons/security/.github/scripts/check_release_not_stuck.py` (repo-agnostic beyond
`WORKFLOW_FILE` and the `GITHUB_REPOSITORY` / `GITHUB_TOKEN` env vars it already reads).

Why this exists
----------------
`release-legal-review.yml` gates its `release` job on the `legal-release` environment, so a
release waits for a human before the moving tag reaches the fleet. That gate is correct.
What it lacks on its own is any alarm for the state "nobody has approved for N days": a run
sits in `waiting` indefinitely, `main` is green, the PR reads as shipped, and the only way to
find out is for somebody to open the Actions tab and go looking.

That is the same shape as the thing the release automation itself was built to end. An
unreleased fix is indistinguishable from a released one from inside the repository; an
unapproved release is indistinguishable from an approved one unless something reads the run
list and says otherwise. The `verify` job's other check proves the tags landed. This proves
nothing is silently queued up behind a human who did not notice they were being asked.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

GITHUB_API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
WORKFLOW_FILE = "release-legal-review.yml"

# A run in one of these has been created and is not running: it is either held by a
# deployment protection rule (`waiting`) or held behind the concurrency group (`queued` /
# `pending`). Both mean the release has not happened, and neither reports itself anywhere.
_HELD_STATUSES = frozenset({"waiting", "queued", "pending", "action_required", "requested"})

# A release nobody has approved overnight is ordinary — the reviewer is asleep. A day later
# it is not, and by then a fix merged behind it has been unreleased for a day with every
# symptom reading as shipped.
DEFAULT_THRESHOLD_HOURS = 24


def _parse_ts(value: str) -> datetime:
    """Parse a GitHub API timestamp into an aware UTC datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def evaluate(runs, now: datetime, threshold_hours: float = DEFAULT_THRESHOLD_HOURS):
    """Pure decision step, so every failure mode is unit-testable without the API.

    `runs` is the API's run list (dicts with at least `id`, `status`, `created_at`). Returns
    (stuck, messages).

    An empty `runs` is an ERROR, never a pass. This check's whole input is the run list;
    finding none means the query broke, the workflow was renamed, or the token lost
    `actions: read` — not that the release path is healthy.
    """
    messages: list[str] = []

    if not runs:
        messages.append(
            f"::error::Found no `{WORKFLOW_FILE}` runs at all. This check reads the Actions "
            f"run list; no runs means the query, the workflow name, or the `actions: read` "
            f"permission changed — not that the release path is healthy. Fix or delete this "
            f"check deliberately."
        )
        return [], messages

    stuck = []
    for run in runs:
        if run.get("status") not in _HELD_STATUSES:
            continue
        created = _parse_ts(run["created_at"])
        held_hours = (now - created).total_seconds() / 3600
        if held_hours < threshold_hours:
            continue
        stuck.append(run)
        messages.append(
            f"::error::Release run {run['id']} has been `{run['status']}` for "
            f"{held_hours:.0f}h (since {run['created_at']}). A release waiting on "
            f"`legal-release` moves no tags, so every reusable merged behind it is "
            f"unreleased while `main` reads as shipped. Approve or cancel it: "
            f"{run.get('html_url', '(no url)')}"
        )

    if not stuck:
        messages.append(
            f"No `{WORKFLOW_FILE}` run has been held longer than {threshold_hours:.0f}h "
            f"({len(runs)} run(s) checked). ✅"
        )
    return stuck, messages


def fetch_runs(repo: str, token: str, per_page: int = 50):
    """The most recent runs of this workflow. Raises rather than returning []."""
    url = (
        f"{GITHUB_API}/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs"
        f"?per_page={per_page}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response).get("workflow_runs", [])


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token:
        print(
            "::error::GITHUB_REPOSITORY and GITHUB_TOKEN are required. Without them this "
            "check cannot read the run list, and it must not pass on that basis.",
            file=sys.stderr,
        )
        return 1

    try:
        runs = fetch_runs(repo, token)
    except (urllib.error.URLError, ValueError, KeyError) as exc:
        # Deliberately not a pass. An unreachable API is an unknown, and this check exists
        # precisely because an unknown was being read as fine.
        print(f"::error::Could not read the {WORKFLOW_FILE} run list: {exc}", file=sys.stderr)
        return 1

    stuck, messages = evaluate(runs, datetime.now(timezone.utc))
    for message in messages:
        print(message)

    return 1 if any(m.startswith("::error::") for m in messages) else 0


if __name__ == "__main__":
    sys.exit(main())
