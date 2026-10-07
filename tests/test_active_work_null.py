"""Regression test for a board whose `activeWork` is JSON null (upstream #868).

`d.setdefault("activeWork", {})` only fills a MISSING key; when the key is
present with value null it returns None, and the next `sid in aw` crashed every
mutating card.py command with `TypeError: argument of type 'NoneType' is not a
container or iterable`. card_commands._active_work_map normalizes null to {}.

Hermetic: card.py runs as a subprocess with BOARD_NO_SERVER=1 (locked direct
write, no network) and HOME pointed at tmp_path, so the last-active pointer it
records lands in a throwaway registry instead of the real ~/.board-steward.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import card_commands

ROOT = Path(__file__).resolve().parent.parent
CARD = ROOT / "scripts" / "card.py"
TEMPLATE = ROOT / "templates" / "board.json"
SID = "test-session-868"


def _seed(tmp_path, **extra):
    b = tmp_path / "board" / "board.json"
    b.parent.mkdir(parents=True)
    shutil.copy(TEMPLATE, b)
    d = json.loads(b.read_text())
    d.update(extra)
    b.write_text(json.dumps(d))
    return b


def _card(tmp_path, board, *args):
    env = {**os.environ, "BOARD_NO_SERVER": "1", "HOME": str(tmp_path),
           "CLAUDE_CODE_SESSION_ID": SID}
    return subprocess.run(
        [sys.executable, str(CARD), "--board", str(board), *args],
        capture_output=True, text=True, env=env,
    )


def test_active_work_map_normalizes_null_in_place():
    d = {"activeWork": None}
    aw = card_commands._active_work_map(d)
    assert aw == {} and d["activeWork"] is aw


def test_active_work_map_keeps_an_existing_map():
    existing = {"s": {"cardId": "c1", "ts": 1}}
    d = {"activeWork": existing}
    assert card_commands._active_work_map(d) is existing


def test_add_and_start_on_a_null_active_work_board(tmp_path):
    b = _seed(tmp_path, activeWork=None)
    r = _card(tmp_path, b, "add", "--column", "task", "--title", "first card")
    assert r.returncode == 0, r.stderr

    r = _card(tmp_path, b, "fly", "1", "inprogress", "--force")
    assert r.returncode == 0, r.stderr

    d = json.loads(b.read_text())
    card = d["cards"][0]
    assert card["column"] == "inprogress"
    assert d["activeWork"][SID]["cardId"] == card["id"]   # the pulse is claimed


def test_legacy_scalar_migrates_onto_a_null_map(tmp_path):
    # pre-#608 boards carry a scalar activeWorkId; lifting it into the map must
    # not crash when the map itself is null
    b = _seed(tmp_path, activeWork=None, activeWorkId="legacy-card")
    r = _card(tmp_path, b, "add", "--column", "task", "--title", "after legacy")
    assert r.returncode == 0, r.stderr
    d = json.loads(b.read_text())
    assert "activeWorkId" not in d
    assert isinstance(d["activeWork"], dict)
