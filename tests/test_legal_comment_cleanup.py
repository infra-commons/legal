"""Pin that the reviewer deletes only its OWN prior comments (infra-commons/meta#1779, L2).

The marker is plain text. Matching it anywhere in a body deleted any comment that quoted a
review, whoever wrote it. The reviewer now deletes a comment only when github-actions[bot]
wrote it and the body starts with the marker, which is how every comment the reviewer posts begins.
"""
import functools
import re
import types

import httpx


def _run_cleanup(reviewer, monkeypatch, comments):
    deleted = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=comments)
        if request.method == "DELETE":
            deleted.append(int(request.url.path.rsplit("/", 1)[1]))
            return httpx.Response(204)
        raise AssertionError(f"unexpected {request.method} {request.url}")

    fake = types.SimpleNamespace(
        Client=functools.partial(httpx.Client, transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(reviewer, "httpx", fake)
    reviewer.delete_previous_comments("t", "o/r", 1)
    return deleted


def _comment(cid, login, body):
    return {"id": cid, "user": {"login": login}, "body": body}


def test_deletes_only_the_bots_own_marked_comments(reviewer, monkeypatch):
    m = reviewer.MARKER
    comments = [
        _comment(1, "github-actions[bot]", f"{m}\n## Legal Review"),   # ours: delete
        _comment(2, "some-human", f"{m}\n## Legal Review"),            # human, marker first
        _comment(3, "some-human", f"> quoting the bot:\n> {m}"),       # human quoting a review
        _comment(4, "github-actions[bot]", f"other workflow, mentions {m}"),  # bot, not first
        _comment(5, "github-actions[bot]", "unrelated bot comment"),
        {"id": 6, "user": None, "body": f"{m}\n## Legal Review"},      # deleted (ghost) user
        _comment(7, "github-actions[bot]", None),
    ]
    assert _run_cleanup(reviewer, monkeypatch, comments) == [1]


def test_posted_body_starts_with_the_marker():
    """The cleanup's `startswith` relies on this; pin it against the shipped source."""
    from conftest import extract_reviewer_source

    src = extract_reviewer_source()
    assert re.search(r'comment_body = \(\n\s*f"\{MARKER\}\\n"', src)
