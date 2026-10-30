"""Pin that every embedded Python heredoc runs isolated, and the Dependabot skip (meta#1778).

M-import: `python3 << 'PYEOF'` reads its program from stdin, so `sys.path[0]` is the cwd. In the
reusables that cwd is a checkout of the caller's code (the PR head, for legal-review), and the
step's env carries the Anthropic key and a write token. A `yaml.py` committed there would import
ahead of the real one. `-I` drops cwd from `sys.path` (and ignores PYTHON* env vars and user
site-packages; the pinned deps are installed into the interpreter's own site-packages).

This walks every workflow, so the next reusable that copies the bare shape fails here.

M-actor: the review is skipped for Dependabot only when Dependabot both opened the PR and
triggered the run. Pinned on both the review job's `if:` and the gate's IS_DEPENDABOT, which must
agree, or the gate passes a skip the review job never made (or blocks one it did).
"""
import re
import subprocess
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS = sorted((_ROOT / ".github/workflows").glob("*.yml"))
_LEGAL_REVIEW = _ROOT / ".github/workflows/legal-review-reusable.yml"

_INVOCATION = re.compile(r"^\s*python3?\b([^\n]*?)<<", re.M)


def _invocations():
    for wf in _WORKFLOWS:
        for m in _INVOCATION.finditer(wf.read_text(encoding="utf-8")):
            yield wf.name, m.group(0).strip(), m.group(1).split()


def test_heredocs_are_found():
    assert len(list(_invocations())) >= 5


def test_every_heredoc_runs_isolated():
    bare = [f"{name}: {line}" for name, line, flags in _invocations() if "-I" not in flags]
    assert not bare, "python heredoc without -I (cwd is on sys.path):\n" + "\n".join(bare)


def test_isolated_flag_keeps_cwd_off_sys_path(tmp_path):
    """Positive control for the flag itself: a planted module in cwd shadows without -I."""
    (tmp_path / "json.py").write_text("raise SystemExit('planted module imported')\n")
    prog = "import json\nprint('real')\n"
    bare = subprocess.run([sys.executable], input=prog, cwd=tmp_path,
                          capture_output=True, text=True)
    iso = subprocess.run([sys.executable, "-I"], input=prog, cwd=tmp_path,
                         capture_output=True, text=True)
    assert "planted module imported" in bare.stderr
    assert iso.returncode == 0 and iso.stdout.strip() == "real"


def _norm(expr: str) -> str:
    return " ".join(str(expr).split())


_DEPENDABOT_RUN = (
    "github.event.pull_request.user.login == 'dependabot[bot]' "
    "&& github.actor == 'dependabot[bot]'"
)


def test_dependabot_skip_needs_author_and_actor():
    jobs = yaml.safe_load(_LEGAL_REVIEW.read_text(encoding="utf-8"))["jobs"]
    review_if = _norm(jobs["legal-review"]["if"])
    gate_env = _norm(jobs["gate"]["steps"][0]["env"]["IS_DEPENDABOT"])
    assert f"!({_DEPENDABOT_RUN})" in review_if
    assert gate_env == f"${{{{ {_DEPENDABOT_RUN} }}}}"
    # No remaining actor-only test on either side.
    for expr in (review_if, gate_env):
        assert "github.actor != 'dependabot[bot]'" not in expr
