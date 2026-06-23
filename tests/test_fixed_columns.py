"""Tests for the #14 fixed 4-lane board (Backlog → To Do → In Progress → Done).

Pins two things:
  1. The canonical lane set is EXACTLY these four, in this order — no super-urgent /
     ideas / notes / discarded lanes anywhere in the defaults or the render/digest
     order hints.
  2. The auto-mechanisms no longer RESURRECT a removed lane: an urgent keyword bumps
     priority but keeps the card in its normal queue (urgency is a priority, not a
     column), and an auto-detected card lands in Backlog (no Ideas lane).

Hermetic: the integration cases run card.py as a subprocess on a throwaway board
with BOARD_NO_SERVER=1, so the locked direct-write path is taken and neither the
network nor the live server on 127.0.0.1:7891 is ever touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import card_commands
import _render
import serve

ROOT = Path(__file__).resolve().parent.parent
CARD = ROOT / "scripts" / "card.py"
TEMPLATE = ROOT / "templates" / "board.json"

CANON = ["backlog", "task", "inprogress", "done"]


# ---- static invariants (no I/O) ------------------------------------------

def test_default_cols_are_the_four_canonical_lanes():
    cols = serve._DEFAULT_COLS
    assert [c["id"] for c in cols] == CANON
    assert [c["name"] for c in cols] == ["Backlog", "To Do", "In Progress", "Done"]
    # the retired lanes must not sneak back into the defaults
    assert not ({"super-urgent", "ideas", "notes", "discarded"} & {c["id"] for c in cols})


def test_template_board_ships_the_four_lanes():
    cols = json.loads(TEMPLATE.read_text())["columns"]
    assert [c["id"] for c in cols] == CANON


def test_render_and_digest_order_put_backlog_first():
    assert _render._ORDER == CANON
    assert card_commands._DIGEST_ORDER == CANON


# ---- integration: auto-mechanisms stay inside the 4 lanes ----------------

def _seed(tmp_path):
    b = tmp_path / "board" / "board.json"
    b.parent.mkdir(parents=True)
    shutil.copy(TEMPLATE, b)
    return b


def _add(board, *args):
    env = {**os.environ, "BOARD_NO_SERVER": "1"}
    return subprocess.run(
        [sys.executable, str(CARD), "--board", str(board), "add", *args],
        capture_output=True, text=True, env=env,
    )


def test_urgent_keyword_does_not_resurrect_super_urgent(tmp_path):
    b = _seed(tmp_path)
    r = _add(b, "--title", "URGENT must fix the parser asap",
             "--origin", "this is critical, a blocker")
    assert r.returncode == 0, r.stderr
    d = json.loads(b.read_text())
    assert [c["id"] for c in d["columns"]] == CANON          # no new lane added
    card = d["cards"][0]
    assert card["column"] == "backlog"                       # not super-urgent
    assert card["priority"] == "critical"                    # urgency → priority


def test_auto_card_lands_in_backlog_not_ideas(tmp_path):
    b = _seed(tmp_path)
    r = _add(b, "--auto", "--title", "maybe add a dark mode")
    assert r.returncode == 0, r.stderr
    d = json.loads(b.read_text())
    assert [c["id"] for c in d["columns"]] == CANON          # no ideas lane added
    assert d["cards"][0]["column"] == "backlog"


def test_fly_to_done_keeps_lane_set_fixed(tmp_path):
    b = _seed(tmp_path)
    assert _add(b, "--title", "ship the thing").returncode == 0
    env = {**os.environ, "BOARD_NO_SERVER": "1"}
    r = subprocess.run(
        [sys.executable, str(CARD), "--board", str(b), "fly", "1", "done"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    d = json.loads(b.read_text())
    assert [c["id"] for c in d["columns"]] == CANON
    assert d["cards"][0]["column"] == "done"
