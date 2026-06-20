"""Containment tests for serve.BoardHandler._handle_archive.

The handler serves GET /archive/<rel> and MUST confine reads to
<board_dir>/archive. We exercise the containment LOGIC directly by building a
bare handler instance (object.__new__, no socket/HTTP machinery) and stubbing
the two output methods so we can record what status / file the handler chose.
"""

import json

import serve


def _make_handler(board_dir):
    """A BoardHandler with only board_dir set and _send / _send_file recording."""
    h = object.__new__(serve.BoardHandler)
    h.board_dir = board_dir
    calls = []

    def fake_send(status, body, ctype="application/json", extra=None):
        calls.append(("send", status, body))

    def fake_send_file(path, ctype, extra=None):
        calls.append(("file", str(path), ctype))

    h._send = fake_send
    h._send_file = fake_send_file
    return h, calls


def _seed_archive(tmp_path):
    """Create archive/ok.json and a sibling archive-secrets/secret.json."""
    arch = tmp_path / "archive"
    arch.mkdir()
    (arch / "ok.json").write_text('{"x": 1}')
    sib = tmp_path / "archive-secrets"
    sib.mkdir()
    (sib / "secret.json").write_text('{"secret": 1}')
    return arch, sib


def test_archive_serves_normal_file(tmp_path):
    """A plain in-tree rel under archive/ is served via _send_file."""
    arch, _ = _seed_archive(tmp_path)
    h, calls = _make_handler(tmp_path)

    h._handle_archive("/archive/ok.json")

    assert len(calls) == 1
    kind, served_path, ctype = calls[0]
    assert kind == "file"
    assert served_path == str((arch / "ok.json").resolve())
    assert ctype == "application/json"


def test_archive_missing_file_returns_404(tmp_path):
    """An in-tree rel that does not exist is a 404 (not a 403, not a serve)."""
    _seed_archive(tmp_path)
    h, calls = _make_handler(tmp_path)

    h._handle_archive("/archive/nope.json")

    assert len(calls) == 1
    kind, status, body = calls[0]
    assert kind == "send"
    assert status == 404
    assert json.loads(body) == {"error": "not found"}


def test_archive_parent_traversal_blocked(tmp_path):
    """A ../../etc escape resolves outside archive/ and is rejected with 403."""
    _seed_archive(tmp_path)
    h, calls = _make_handler(tmp_path)

    h._handle_archive("/archive/../../etc/passwd")

    assert len(calls) == 1
    kind, status, body = calls[0]
    assert kind == "send"
    assert status == 403
    assert json.loads(body) == {"error": "forbidden"}


def test_archive_directory_relative_traversal_blocked(tmp_path):
    """A rel that climbs out then back into a deep path stays blocked (403)."""
    _seed_archive(tmp_path)
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "leak.json").write_text('{"leak": 1}')
    h, calls = _make_handler(tmp_path)

    h._handle_archive("/archive/../outside/leak.json")

    assert len(calls) == 1
    kind, status, _ = calls[0]
    assert kind == "send"
    assert status == 403


def test_archive_sibling_dir_prefix_bypass(tmp_path):
    """SECURITY INVARIANT: a sibling dir sharing the 'archive' name prefix must
    NOT be readable. The old guard used str(target).startswith(archive) with no
    segment boundary, so '<board>/archive-secrets/secret.json' slipped through;
    containment is now anchored on a path-segment boundary (base in parents).
    """
    _, sib = _seed_archive(tmp_path)
    h, calls = _make_handler(tmp_path)

    h._handle_archive("/archive/../archive-secrets/secret.json")

    assert len(calls) == 1
    kind, status, body = calls[0]
    # The SECURE expectation: this should be forbidden.
    assert kind == "send"
    assert status == 403
