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

_BEGIN = "python3 << 'PYEOF'"
_END = "PYEOF"


def extract_reviewer_source(workflow_path: Path = WORKFLOW) -> str:
    """Return the dedented Python source of the embedded reviewer."""
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


@pytest.fixture(scope="session")
def reviewer():
    """The reviewer module, exec'd from the workflow heredoc."""
    src = extract_reviewer_source()
    mod = types.ModuleType("legal_reviewer_shipped")
    mod.__dict__["__name__"] = "legal_reviewer_shipped"  # keep main() from running
    sys.modules["legal_reviewer_shipped"] = mod
    exec(compile(src, str(WORKFLOW), "exec"), mod.__dict__)
    return mod
