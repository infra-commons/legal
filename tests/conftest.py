"""Load the legal-review reviewer script straight out of the shipped workflow.

The reviewer is embedded as a `python3 << 'PYEOF'` heredoc inside
`.github/workflows/legal-review-reusable.yml`. Tests exec THAT text -- never a
copy -- so a test can only pass against the code the fleet actually runs.
"""
from __future__ import annotations

import os
import sys
import textwrap
import types
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

# `ci` is derandomised on purpose: a property test must never fail a PR that an
# identical rerun would pass. Broader randomised exploration happens locally
# under `dev`.
_HEALTH = [HealthCheck.function_scoped_fixture]
settings.register_profile("ci", derandomize=True, deadline=None, suppress_health_check=_HEALTH)
settings.register_profile("dev", deadline=None, suppress_health_check=_HEALTH)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "legal-review-reusable.yml"
CAPTURE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "legal-capture-findings-reusable.yml"

_BEGIN = "python3 << 'PYEOF'"
_END = "PYEOF"


def extract_reviewer_source(workflow_path: Path = WORKFLOW) -> str:
    """Return the dedented Python source of a workflow's embedded heredoc.

    Parameterised over the workflow so the capture reusable can be loaded the
    same way. The "exactly one heredoc" assertion below is per-file and still
    holds for both: it is what stops this silently extracting the wrong block if
    a second heredoc is ever added.
    """
    lines = workflow_path.read_text(encoding="utf-8").splitlines()

    begins = [i for i, ln in enumerate(lines) if ln.strip() == _BEGIN]
    if len(begins) != 1:
        raise AssertionError(
            f"expected exactly 1 {_BEGIN!r} in {workflow_path.name}, found {len(begins)}"
        )
    start = begins[0]

    ends = [i for i in range(start + 1, len(lines)) if lines[i].strip() == _END]
    if not ends:
        raise AssertionError(f"unterminated heredoc in {workflow_path.name}")
    end = ends[0]

    body = textwrap.dedent("\n".join(lines[start + 1 : end]))
    if not body.strip():
        raise AssertionError("extracted reviewer source is empty")
    return body


def _exec_workflow_module(workflow_path: Path, name: str):
    """Exec a workflow's embedded heredoc as a module, from the shipped YAML."""
    src = extract_reviewer_source(workflow_path)
    mod = types.ModuleType(name)
    mod.__dict__["__name__"] = name  # keep main() from running
    sys.modules[name] = mod
    exec(compile(src, str(workflow_path), "exec"), mod.__dict__)
    return mod


@pytest.fixture(scope="session")
def reviewer():
    """The reviewer module, exec'd from the workflow heredoc."""
    return _exec_workflow_module(WORKFLOW, "legal_reviewer_shipped")


@pytest.fixture(scope="session")
def capture():
    """The post-merge capture module, exec'd from ITS workflow heredoc.

    Added because the suppression matcher — the one that decides whether a
    finding is filed at all — lives here, not in the reviewer, and was therefore
    outside every test in this repo. A wildcard suppression bug sat in it
    unnoticed while the reviewer beside it was well covered.
    """
    return _exec_workflow_module(CAPTURE_WORKFLOW, "legal_capture_shipped")
