"""Unit tests for board revision compare-and-swap (lost-update protection).

Targets:
  serve.py        _disk_rev(board_path) -> int          (authoritative on-disk rev)
  card_state.py   _current_rev(p) -> int | None         (rev or None if unreadable)
  card_state.py   _assert_base_rev(p, base_rev) -> None  (raises BoardConflict on miss)

Behavior is ground-truthed by actually running the functions; see notes inline
where serve and card_state diverge (the rev:null case).
"""
import json
from pathlib import Path

import pytest

import serve
import card_state
from card_state import BoardConflict


# ---- helpers ---------------------------------------------------------------

def write_board(p: Path, data: dict) -> Path:
    p.write_text(json.dumps(data))
    return p


def board_with_rev(tmp_path: Path, rev) -> Path:
    return write_board(tmp_path / "board.json", {"rev": rev, "cards": []})


# ---- serve._disk_rev -------------------------------------------------------

def test_disk_rev_reads_normal_board(tmp_path):
    p = board_with_rev(tmp_path, 7)
    assert serve._disk_rev(p) == 7


def test_disk_rev_missing_file_returns_minus_one(tmp_path):
    # Best-effort sentinel: -1 never equals a real base, so a CAS using it
    # rejects (safe). Documented contract in the docstring.
    assert serve._disk_rev(tmp_path / "nope.json") == -1


def test_disk_rev_malformed_json_returns_minus_one(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    assert serve._disk_rev(p) == -1


def test_disk_rev_missing_rev_key_defaults_zero(tmp_path):
    p = write_board(tmp_path / "board.json", {"cards": []})
    assert serve._disk_rev(p) == 0


# ---- card_state._current_rev ----------------------------------------------

def test_current_rev_reads_normal_board(tmp_path):
    p = board_with_rev(tmp_path, 12)
    assert card_state._current_rev(p) == 12


def test_current_rev_missing_or_malformed_returns_none(tmp_path):
    # None means "can't compare" -> callers skip the CAS check rather than
    # false-conflict (e.g. first-ever write before the file exists).
    assert card_state._current_rev(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    assert card_state._current_rev(bad) is None


# ---- card_state._assert_base_rev (the CAS invariant) -----------------------

def test_assert_base_rev_equal_does_not_raise(tmp_path):
    p = board_with_rev(tmp_path, 5)
    # on-disk rev == base we loaded -> no conflict, returns None.
    assert card_state._assert_base_rev(p, 5) is None


def test_assert_base_rev_advanced_raises_conflict(tmp_path):
    # Another writer bumped disk past our base -> lost-update protection fires.
    p = board_with_rev(tmp_path, 9)
    with pytest.raises(BoardConflict):
        card_state._assert_base_rev(p, 3)


def test_assert_base_rev_unreadable_does_not_raise(tmp_path):
    # _current_rev is None (missing / torn) -> skip the check, never false-conflict.
    missing = tmp_path / "nope.json"
    assert card_state._assert_base_rev(missing, 99) is None

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    assert card_state._assert_base_rev(bad, 99) is None


def test_rev_null_diverges_disk_vs_current(tmp_path):
    # Ground-truth quirk: with {"rev": null}, serve._disk_rev coerces to 0
    # (via `or 0`), but card_state._current_rev returns None (it only defaults
    # when the key is *absent*, not when present-but-null). Documenting the
    # real, divergent behavior rather than what one might assume.
    p = write_board(tmp_path / "board.json", {"rev": None})
    assert serve._disk_rev(p) == 0
    assert card_state._current_rev(p) is None
    # Consequence: a null rev makes _assert_base_rev a no-op (None -> skip),
    # so it never raises regardless of base_rev.
    assert card_state._assert_base_rev(p, 12345) is None
