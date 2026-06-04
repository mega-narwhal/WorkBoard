#!/usr/bin/env python3
"""hourly_extractor card emission + progress banner — extracted from hourly_extractor.py (#307).

How discovered cards and the progress banner get written to the board (all via
card.py subprocess). A pure leaf: nothing here calls back into the extractor,
reconciler, or digest builder, so both hourly_extractor and hourly_reconcile
import it freely.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _banner_update_text(card_py: Path, board: Path, num: int, title: str) -> None:
    args = [sys.executable, str(card_py), "--board", str(board), "update",
            str(num), "--title", title]
    try:
        subprocess.run(args, capture_output=True, text=True, timeout=4)
    except subprocess.SubprocessError:
        pass


# ---------- progress banner ----------

def _emit_progress(card_py: Path, board: Path, done: int, total: int,
                   label: str = "", phase: str = "") -> None:
    """#318 — drive the live BOARD-LOAD HUD via `card.py progress` (best-effort).
    phase (#327) sets the HUD header: replay / speedup / solo / inline('')."""
    try:
        subprocess.run(
            [sys.executable, str(card_py), "--board", str(board), "progress",
             "--done", str(done), "--total", str(total), "--label", label,
             "--phase", phase],
            capture_output=True, text=True, timeout=4)
    except subprocess.SubprocessError:
        pass


def _banner_create(card_py: Path, board: Path, total_chunks: int,
                   phase: str = "") -> int | None:
    """Kick off extraction progress on the live BOARD-LOAD HUD.

    The HUD (#318) is the single source of truth for "X/Y chunks". The old
    'notes'-column banner card was redundant with it (user, 2026-06-01), so it's
    gone — we only drive the HUD here and return None (no banner card to update).
    """
    _emit_progress(card_py, board, 0, total_chunks,
                   "staged — beginning extraction…", phase)
    return None


def _banner_update(card_py: Path, board: Path, num: int,
                   done: int, total: int, cards_so_far: int,
                   phase: str = "", label_override: str | None = None) -> None:
    # The notes-column banner card is gone (num is None) — progress lives only
    # on the HUD now. #327 — label_override lets the tier-1→tier-2 handoff
    # replace the generic "chunk N/M" line with e.g. "day-1 replayed in 8s ▸▸".
    _emit_progress(card_py, board, done, total,
                   label_override or f"chunk {done}/{total} · {cards_so_far} cards emitted",
                   phase)


def _banner_finish(card_py: Path, board: Path, num: int,
                   n_cards: int, n_buckets: int, n_chunks: int,
                   n_moved: int = 0) -> None:
    # The notes-column banner card is gone — nothing to finalize. The HUD's
    # final state is driven by the last _banner_update / the HUD's own done
    # handling. Kept as a no-op so callers don't need to change.
    return None


def _card_add(card_py: Path, board: Path, card: dict) -> int | None:
    title = (card.get("title") or "").strip()[:80]
    if not title:
        return None
    code = (card.get("code") or "").strip()
    # The code renders as its own badge — keep the title CLEAN (no "CODE: " prefix),
    # matching the manual board (code 'BOARD-AUTO-MOVE' + title 'Auto-promotion …').
    # Strip a redundant leading "CODE:" if the LLM put one in the title.
    if code and title.lower().startswith(code.lower()):
        title = title[len(code):].lstrip(" :—-").strip() or title
    column = card.get("column") or "task"
    if column not in ("task", "backlog", "inprogress", "done",
                      "mandatory", "notes"):
        column = "task"
    priority = card.get("priority") or "mid"
    if priority not in ("low", "mid", "critical"):
        priority = "mid"
    notes = (card.get("notes") or "").strip()[:400]
    tags = card.get("tags") or []
    origin = card.get("origin") or f"Hourly extract — bucket {card.get('_bucket_label','')}"

    args = [sys.executable, str(card_py), "--board", str(board), "add",
            "--column", column, "--priority", priority,
            "--title", title, "--origin", origin[:400],
            "--tag", "discovered"]
    # Set the code FIELD (not just the title prefix) so the colored code badge
    # renders on the card — matching the manual board (e.g. SIM-60D, BOARD-SLIM).
    if code:
        args += ["--code", code[:24]]
    # Stamp createdAt with the bucket's actual time so the board sorts
    # chronologically without an end-pass.
    bucket_ts = card.get("_bucket_ts_iso")
    if bucket_ts:
        args += ["--created-at", bucket_ts]
    if notes:
        args += ["--notes", notes]
    for t in tags:
        if isinstance(t, str) and t.strip():
            args += ["--tag", t.strip()]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=8)
    except subprocess.SubprocessError:
        return None
    if out.returncode != 0:
        return None
    m = re.search(r"#(\d+)", out.stdout)
    return int(m.group(1)) if m else None


def _card_fly(card_py: Path, board: Path, num: int, col: str,
              writeup: str | None = None, bug: str | None = None,
              improve: str | None = None, subtask: str | None = None) -> bool:
    args = [sys.executable, str(card_py), "--board", str(board), "fly",
            str(num), col, "--pause-ms", "150"]
    if writeup:
        args += ["--writeup", writeup[:200]]
    if bug:
        args += ["--bug", bug[:120]]
    if improve:
        args += ["--improve", improve[:120]]
    if subtask:
        args += ["--subtask", subtask[:120]]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=8)
    except subprocess.SubprocessError:
        return False
    return out.returncode == 0


def _replay_transitions(card_py: Path, board: Path, num: int,
                         transitions, pace_s: float) -> int:
    """Replay the richer historical path (#294 SIM-RICH-LIFECYCLE) — extra hops
    AFTER the initial ship: a `bug` reopen flies done→IP with a 🐞 subtask; an
    `improve` reopen flies done→IP with an improvement subtask; a `done` hop
    closes the cycle. The card.py fly --bug/--improve flags do the tag+subtask
    bookkeeping; history[] (#258) records every hop. Returns hops replayed.
    Silently ignores malformed entries so a bad LLM field can't break the fill."""
    if not isinstance(transitions, list):
        return 0
    hops = 0
    for t in transitions:
        if not isinstance(t, dict):
            continue
        to = t.get("to")
        if to not in ("inprogress", "done"):
            continue
        kind = t.get("kind")
        reason = (t.get("reason") or "").strip()
        time.sleep(pace_s)
        if to == "inprogress" and kind == "bug":
            ok = _card_fly(card_py, board, num, "inprogress", bug=reason or "regression after ship")
        elif to == "inprogress" and kind == "improve":
            ok = _card_fly(card_py, board, num, "inprogress", improve=reason or "enhancement after ship")
        elif to == "inprogress":
            ok = _card_fly(card_py, board, num, "inprogress")
        else:  # done — closes the reopened cycle
            ok = _card_fly(card_py, board, num, "done", writeup=reason or "shipped (replay)")
        hops += 1 if ok else 0
    return hops


def emit_card(card_py: Path, board: Path, card: dict,
              show_lifecycle: bool, pace_s: float) -> int | None:
    """Add the card, then optionally walk lifecycle hops if show_lifecycle."""
    final_col = card.get("column") or "task"
    if show_lifecycle and final_col in ("done", "inprogress"):
        # Start in task → fly to final
        card_for_add = dict(card)
        card_for_add["column"] = "task"
        num = _card_add(card_py, board, card_for_add)
        if num is None:
            return None
        time.sleep(pace_s)
        if final_col == "done":
            _card_fly(card_py, board, num, "inprogress")
            time.sleep(pace_s)
            _card_fly(card_py, board, num, "done",
                      writeup=card.get("notes") or "shipped (replay)")
            # #294: reconstruct the true post-ship path (bug bounces / improves)
            _replay_transitions(card_py, board, num, card.get("transitions"), pace_s)
        else:  # inprogress
            _card_fly(card_py, board, num, "inprogress")
        return num
    else:
        return _card_add(card_py, board, card)



__all__ = [
    "_banner_update_text", "_banner_create", "_banner_update", "_banner_finish",
    "_emit_progress", "_card_add", "_card_fly", "_replay_transitions", "emit_card",
]
