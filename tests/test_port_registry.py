"""Hermetic unit tests for port_registry.

port_registry is FILE-BACKED: it persists a sticky board->port designation
map (BOARD_ASSIGNMENTS) and a separate liveness registry (BOARD_REGISTRY).
Every test points BOTH env vars at tmp_path so the real $HOME registry is
provably untouched and nothing escapes the sandbox.
"""

import os
from pathlib import Path

import port_registry as pr


def _env(monkeypatch, tmp_path):
    """Redirect both file-backed stores into tmp_path. Returns the dir."""
    assign = tmp_path / "port-assignments.json"
    registry = tmp_path / "port-registry.json"
    monkeypatch.setenv("BOARD_ASSIGNMENTS", str(assign))
    monkeypatch.setenv("BOARD_REGISTRY", str(registry))
    return tmp_path


def _board(tmp_path, name):
    """A real on-disk board dir (assign GCs designations whose dir vanished)."""
    d = tmp_path / name
    d.mkdir()
    return str(d)


def test_assignments_path_isolated_to_tmp(monkeypatch, tmp_path):
    # The whole point of isolation: assignments_path() must land inside tmp_path,
    # never the real ~/.board-steward registry.
    root = _env(monkeypatch, tmp_path)
    p = pr.assignments_path()
    assert str(p).startswith(str(root))
    assert ".board-steward" not in str(p)


def test_assign_writes_only_to_env_path_not_home(monkeypatch, tmp_path):
    # Hermeticity proof: a real assign() must materialize the assignments file
    # at the BOARD_ASSIGNMENTS env path and NOTHING under the module's default
    # ~/.board-steward path. We also point HOME at an empty tmp dir and assert
    # the default path is never created.
    _env(monkeypatch, tmp_path)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    pr.assign(_board(tmp_path, "iso"))
    # The env-directed file exists ...
    assert pr.assignments_path().exists()
    assert str(pr.assignments_path()).startswith(str(tmp_path))
    # ... and the default ~/.board-steward tree was never touched.
    assert not (fake_home / ".board-steward").exists()


def test_assign_returns_port_in_window_and_is_sticky(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    board = _board(tmp_path, "boardA")
    port = pr.assign(board)
    assert pr.PORT_LO <= port <= pr.PORT_HI
    # Sticky: same board_dir -> same port on a second call.
    assert pr.assign(board) == port
    # And it persisted into the assignments map (keyed by resolved abspath).
    assert pr.assignments()[str(Path(board).resolve())] == port


def test_assign_two_boards_get_distinct_ports(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    p1 = pr.assign(_board(tmp_path, "b1"))
    p2 = pr.assign(_board(tmp_path, "b2"))
    assert p1 != p2
    # Lowest-free-first allocation from PORT_LO upward.
    assert p1 == pr.PORT_LO
    assert p2 == pr.PORT_LO + 1


def test_assign_preferred_honored_when_free(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    board = _board(tmp_path, "pref")
    assert pr.assign(board, preferred=7950) == 7950


def test_assign_preferred_ignored_when_taken(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    first = pr.assign(_board(tmp_path, "first"))  # claims PORT_LO
    # PORT_LO is now taken; asking for it as preferred must fall through to the
    # next free port, NOT collide.
    second = pr.assign(_board(tmp_path, "second"), preferred=first)
    assert second != first
    assert second == pr.PORT_LO + 1


def test_assign_gcs_vanished_board_and_reclaims_its_slot(monkeypatch, tmp_path):
    # Documented self-heal: assign() drops designations whose board dir no
    # longer exists, so a NEW board reclaims the freed (lowest) port instead of
    # the window slowly filling with dead projects (#374).
    _env(monkeypatch, tmp_path)
    import shutil
    b1 = _board(tmp_path, "gone")
    b2 = _board(tmp_path, "stays")
    p1 = pr.assign(b1)            # PORT_LO
    p2 = pr.assign(b2)            # PORT_LO + 1
    shutil.rmtree(b1)            # b1's dir vanishes
    p3 = pr.assign(_board(tmp_path, "fresh"))
    # Fresh board reclaims b1's freed slot; b1's stale designation is gone.
    assert p3 == p1
    assert str(Path(b1).resolve()) not in pr.assignments()
    assert pr.assignments()[str(Path(b2).resolve())] == p2


def test_lookup_unknown_is_none_and_assigned_after_write(monkeypatch, tmp_path):
    # lookup() reads the LIVENESS registry (BOARD_REGISTRY), which is distinct
    # from the assignment map. So assign() alone does NOT make lookup() resolve;
    # a serve.py write() does. Capture that real two-store contract.
    _env(monkeypatch, tmp_path)
    board = _board(tmp_path, "live")
    assert pr.lookup(board) is None
    port = pr.assign(board)
    assert pr.lookup(board) is None  # designation != live registration
    pr.write(board, port, os.getpid())
    assert pr.lookup(board) == port


def test_assignments_empty_when_no_file(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    # Nothing assigned yet -> empty dict, no crash on missing file.
    assert pr.assignments() == {}
