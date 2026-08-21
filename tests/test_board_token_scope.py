"""Pin the `board-token` step's permission scope (infra-commons/meta#661).

`create-github-app-token` replaces the App install's full grant with exactly the `permission-*`
inputs given — it does not narrow additively. If the `board-token` step ever requested only
`organization-projects: write`, the minted token would carry zero `issues` scope, and
`addProjectV2ItemById`'s `contentId` (the issue this same job just created) could never resolve.
That fails as `NOT_FOUND` on a node that plainly exists, one log line, job still exits 0 —
indistinguishable from "no findings this run" (this is the exact bug rolliq-com/operations#242
carried before its fix was inherited here).

This test exists so a future edit to this step can't drop `permission-issues` again (e.g. while
"cleaning up" the `with:` block) without anyone noticing until the same silent failure recurs.
"""
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github/workflows/legal-capture-findings-reusable.yml"


def _board_token_step():
    jobs = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    for job in jobs.values():
        for step in job.get("steps", []):
            if step.get("id") == "board-token":
                return step
    raise AssertionError("no step with id 'board-token' found in legal-capture-findings-reusable.yml")


def test_board_token_requests_organization_projects_write():
    with_block = _board_token_step()["with"]
    assert with_block.get("permission-organization-projects") == "write", (
        "the board-add mutation needs write access to the org Project"
    )


def test_board_token_also_requests_issues_read():
    # The regression this test exists to catch: this key silently disappearing while
    # `permission-organization-projects` above stays intact.
    with_block = _board_token_step()["with"]
    assert with_block.get("permission-issues") == "read", (
        "without this, addProjectV2ItemById cannot resolve the issue node it was just handed, "
        "and fails as NOT_FOUND indistinguishable from a genuinely absent node"
    )


def test_board_token_step_is_guarded_and_never_fails_the_job():
    # A secret this org hasn't provisioned yet must not touch the job's outcome — see the
    # optional `INFRA_COMMONS_BOT_PRIVATE_KEY` secret and BOARD_APP_KEY env guard above it.
    step = _board_token_step()
    assert step.get("if") == "${{ env.BOARD_APP_KEY != '' }}"
    assert step.get("continue-on-error") is True


def test_the_secret_stays_optional():
    doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML parses the bare `on:` key as the boolean True (YAML 1.1's on/off/yes/no resolver),
    # not the string "on" -- this is not a typo.
    secrets = doc[True]["workflow_call"]["secrets"]
    assert secrets["INFRA_COMMONS_BOT_PRIVATE_KEY"]["required"] is False, (
        "this must ship inert in every caller until it separately opts in by forwarding the "
        "secret — flipping this to required breaks every caller that hasn't"
    )
