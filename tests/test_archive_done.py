"""Tests for archive_done.py — the Done-card archival backstop.

Exercises the real CLI end-to-end on throwaway boards: which Done cards are old
enough to archive, monthly bucketing, the "never delete" invariant, and the
server-safe save (BOARD_NO_SERVER=1 forces the locked direct-write + rev-CAS
path, so no network / no live server is touched). Hermetic: every board lives
under tmp_path.

Dates are computed RELATIVE to now (the archiver's cutoff is now - --days), so
the suite stays correct whenever it runs — never hard-code a calendar date.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parent.parent / "scripts" / "archive_done.py"


def _ago(days):
    """ISO-Z timestamp `days` days before now (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _month(days):
    """The board-YYYY-MM bucket key a card `days` old lands in."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m")


def _board(rev=5, cards=None):
    return {
        "rev": rev,
        "columns": [
            {"id": "task", "name": "Task"},
            {"id": "inprogress", "name": "In Progress"},
            {"id": "done", "name": "Done"},
        ],
        "cards": cards or [],
    }


def _done(cid, days_ago, num=None):
    return {"id": cid, "num": num, "title": f"card {cid}", "column": "done", "doneAt": _ago(days_ago)}


def _write(tmp_path, board):
    bp = tmp_path / "board" / "board.json"
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps(board, indent=2))
    return bp


def _run(bp, *args):
    """Run the archiver CLI hermetically (no server, forced direct write)."""
    env = {**os.environ, "BOARD_NO_SERVER": "1"}
    return subprocess.run(
        [sys.executable, str(ARCHIVE), str(bp), *args],
        capture_output=True, text=True, env=env, timeout=30,
    )


def _load(bp):
    return json.loads(bp.read_text())


def _archive_files(bp):
    adir = bp.parent / "archive"
    return sorted(p.name for p in adir.glob("*.json")) if adir.is_dir() else []


# --- selection -------------------------------------------------------------

def test_archives_done_older_than_cutoff(tmp_path):
    bp = _write(tmp_path, _board(cards=[
        _done("old", 60, 1),
        _done("recent", 1, 2),
        {"id": "open", "num": 3, "title": "open", "column": "task"},
    ]))
    r = _run(bp, "--days", "14")
    assert r.returncode == 0, r.stderr
    active = {c["id"] for c in _load(bp)["cards"]}
    # old Done leaves the active board; recent Done and the open task stay.
    assert active == {"recent", "open"}
    assert _archive_files(bp) == [f"board-{_month(60)}.json"]
    archived = json.loads((bp.parent / "archive" / f"board-{_month(60)}.json").read_text())
    assert [c["id"] for c in archived["cards"]] == ["old"]


def test_card_exactly_inside_window_is_kept(tmp_path):
    # 13 days old with a 14-day cutoff → still recent, must stay.
    bp = _write(tmp_path, _board(cards=[_done("borderline", 13, 1)]))
    r = _run(bp, "--days", "14")
    assert r.returncode == 0, r.stderr
    assert {c["id"] for c in _load(bp)["cards"]} == {"borderline"}
    assert _archive_files(bp) == []


def test_done_without_doneat_is_not_archived(tmp_path):
    # No doneAt → age is unknowable → must stay (never guess it's old).
    bp = _write(tmp_path, _board(cards=[
        {"id": "nodate", "num": 1, "title": "done but no doneAt", "column": "done"},
    ]))
    r = _run(bp, "--days", "14")
    assert r.returncode == 0, r.stderr
    assert {c["id"] for c in _load(bp)["cards"]} == {"nodate"}
    assert _archive_files(bp) == []


def test_non_done_cards_are_never_archived(tmp_path):
    # Ancient cards that simply aren't in `done` must not be touched.
    bp = _write(tmp_path, _board(cards=[
        {"id": "ancient-task", "num": 1, "title": "t", "column": "task", "doneAt": _ago(900)},
        {"id": "ancient-ip", "num": 2, "title": "ip", "column": "inprogress", "doneAt": _ago(900)},
    ]))
    r = _run(bp, "--days", "14")
    assert r.returncode == 0, r.stderr
    assert {c["id"] for c in _load(bp)["cards"]} == {"ancient-task", "ancient-ip"}
    assert _archive_files(bp) == []


# --- invariants ------------------------------------------------------------

def test_nothing_is_ever_deleted(tmp_path):
    cards = [
        _done("o1", 70, 1),
        _done("o2", 40, 2),
        _done("recent", 2, 3),
        {"id": "open", "num": 4, "title": "open", "column": "task"},
    ]
    bp = _write(tmp_path, _board(cards=cards))
    r = _run(bp, "--days", "14")
    assert r.returncode == 0, r.stderr
    active_ids = {c["id"] for c in _load(bp)["cards"]}
    archived_ids = set()
    for name in _archive_files(bp):
        for c in json.loads((bp.parent / "archive" / name).read_text())["cards"]:
            archived_ids.add(c["id"])
    # Every original card is accounted for — active ∪ archived == original, no loss.
    assert active_ids | archived_ids == {"o1", "o2", "recent", "open"}
    assert active_ids & archived_ids == set()  # and never both places


def test_monthly_bucketing(tmp_path):
    # 40d and 80d apart guarantees two distinct month buckets (a month is ≤31d).
    bp = _write(tmp_path, _board(cards=[
        _done("a", 40, 1),
        _done("b", 80, 2),
    ]))
    r = _run(bp, "--days", "14")
    assert r.returncode == 0, r.stderr
    assert _archive_files(bp) == sorted({f"board-{_month(40)}.json", f"board-{_month(80)}.json"})


def test_merge_into_existing_archive_dedups(tmp_path):
    bp = _write(tmp_path, _board(cards=[_done("dup", 40, 1)]))
    adir = bp.parent / "archive"
    adir.mkdir(parents=True)
    month = _month(40)
    # Pre-seed the month file already containing the same card id.
    (adir / f"board-{month}.json").write_text(json.dumps({
        "monthKey": month,
        "cards": [{"id": "dup", "num": 1, "title": "card dup", "column": "done", "doneAt": _ago(40)}],
    }))
    r = _run(bp, "--days", "14")
    assert r.returncode == 0, r.stderr
    archived = json.loads((adir / f"board-{month}.json").read_text())
    assert [c["id"] for c in archived["cards"]] == ["dup"]  # not duplicated


# --- behaviour -------------------------------------------------------------

def test_dry_run_changes_nothing(tmp_path):
    bp = _write(tmp_path, _board(cards=[_done("old", 60, 1)]))
    before = bp.read_text()
    r = _run(bp, "--days", "14", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert bp.read_text() == before          # board untouched
    assert _archive_files(bp) == []          # no archive written


def test_rev_is_bumped_on_archive(tmp_path):
    bp = _write(tmp_path, _board(rev=5, cards=[_done("old", 60, 1)]))
    r = _run(bp, "--days", "14")
    assert r.returncode == 0, r.stderr
    # atomic_save bumps the rev so live clients see the change.
    assert _load(bp)["rev"] == 6


def test_noop_when_nothing_is_old_enough(tmp_path):
    bp = _write(tmp_path, _board(rev=5, cards=[_done("recent", 1, 1)]))
    before = bp.read_text()
    r = _run(bp, "--days", "14")
    assert r.returncode == 0, r.stderr
    assert "nothing to archive" in r.stdout.lower()
    assert bp.read_text() == before          # untouched, rev not bumped
    assert _archive_files(bp) == []
