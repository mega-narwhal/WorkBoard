#!/usr/bin/env python3
"""Subagent auto-card backstop — the "every task labelled regardless of source" guarantee.

Wired to TWO Claude Code hook events:
  spawn  <- PreToolUse(matcher 'Agent')  : a subagent is being launched
  stop   <- SubagentStop                 : a subagent just finished

PreToolUse(Agent) payload (stdin):
    {hook_event_name, tool_name:'Agent',
     tool_input:{description, subagent_type, prompt, ...}, cwd, ...}
SubagentStop payload (stdin):
    {session_id, transcript_path, cwd, stop_hook_active, ...}

Design (matches project_agent_to_agent_next.md):
  - Subagents have no UserPromptSubmit/Stop the board watches, so they never
    auto-card on their own. These two hooks close that gap WITHOUT the subagent
    needing to know the board protocol — the carding is done BY the hook,
    autonomously.
  - Full fly: spawn -> card born in 'task', flown to 'inprogress'; stop -> flown
    to 'done'. board.html animates each move live.
  - Read-only subagent types (Explore/Plan) are SKIPPED (no card) — but still
    pushed to the FIFO queue as a skip-marker so spawn<->stop stays aligned when
    read-only and working subagents interleave sequentially.
  - Correlation = a FIFO sidecar queue (board/.subagent_queue.jsonl). Correct
    for SEQUENTIAL subagents (the `claude -p` agent-to-agent loop, the headline
    case). Parallel / background subagents finish out of order -> a card still
    flies to done, but its writeup may pair with the wrong sibling. This is
    LOGGED in the writeup, never silently hidden.
  - At stop, the subagent's transcript is scanned for nested Agent spawns
    (surfaced as a subtask) and explicit bug markers (surfaced in the writeup).
    Bugs are NOT auto-tagged from soft heuristics — only flagged for review — so
    we never invent defect cards (no guessing).

Silent-fail, exit 0 always. Never blocks the subagent.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Subagent types that are pure read-only recon — not carded (user choice).
SKIP_TYPES = {"explore", "plan"}

QUEUE_NAME = ".subagent_queue.jsonl"
NUM_RE = re.compile(r"#(\d+)")
# Conservative, explicit-only bug markers in the subagent's OWN output.
BUG_MARKERS = ("bug:", "regression:", "traceback (most recent call last)")
EDIT_TOOLS = {"edit", "write", "multiedit", "notebookedit"}


def find_board(start: Path) -> Path | None:
    cur = start.resolve()
    for _ in range(8):
        cand = cur / "board" / "board.json"
        if cand.is_file():
            return cand
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def run_card(board: Path, args: list[str]) -> str:
    """Invoke card.py (sibling of this file) against an explicit board. Best-effort."""
    card_py = Path(__file__).resolve().parent / "card.py"
    try:
        cp = subprocess.run(
            [sys.executable, str(card_py), "--board", str(board), *args],
            capture_output=True, text=True, timeout=5,
        )
        return (cp.stdout or "") + (cp.stderr or "")
    except Exception:
        return ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def queue_path(board: Path) -> Path:
    return board.parent / QUEUE_NAME


def queue_push(board: Path, entry: dict) -> None:
    try:
        with queue_path(board).open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def queue_pop(board: Path) -> dict | None:
    """Pop the oldest entry (FIFO). Rewrites the file without its first line."""
    qp = queue_path(board)
    try:
        lines = [ln for ln in qp.read_text(errors="replace").splitlines() if ln.strip()]
    except OSError:
        return None
    if not lines:
        return None
    first, rest = lines[0], lines[1:]
    try:
        qp.write_text(("\n".join(rest) + "\n") if rest else "")
    except OSError:
        pass
    try:
        return json.loads(first)
    except Exception:
        return None


# ---- spawn (PreToolUse 'Agent') --------------------------------------------

def do_spawn(payload: dict) -> None:
    if (payload.get("tool_name") or "").lower() != "agent":
        return
    ti = payload.get("tool_input") or {}
    desc = (ti.get("description") or "subagent task").strip()[:80]
    stype = (ti.get("subagent_type") or "subagent").strip()
    prompt = (ti.get("prompt") or "").strip().replace("\n", " ")[:200]
    cwd = payload.get("cwd") or ""
    if not cwd:
        return
    board = find_board(Path(cwd))
    if board is None:
        return

    # Read-only recon -> don't card, but keep FIFO aligned with a skip marker.
    if stype.lower() in SKIP_TYPES:
        queue_push(board, {"skip": True, "type": stype, "desc": desc, "ts": _now()})
        return

    out = run_card(board, [
        "add", "--column", "task",
        "--title", f"{desc}",
        "--tag", "subagent", "--tag", stype,
        "--origin", f"[subagent:{stype}] {prompt}",
    ])
    m = NUM_RE.search(out)
    if not m:
        # Card add failed — record a skip marker so the matching stop is a no-op
        # rather than popping (and flying) some unrelated card.
        queue_push(board, {"skip": True, "type": stype, "desc": desc,
                           "ts": _now(), "note": "add-failed"})
        return
    num = m.group(1)
    run_card(board, ["fly", num, "inprogress", "--pause-ms", "120"])
    queue_push(board, {"card": num, "type": stype, "desc": desc, "ts": _now()})


# ---- stop (SubagentStop) ---------------------------------------------------

def scan_subagent_transcript(path: Path) -> dict:
    """Tally a finished subagent's transcript: nested spawns, edits, bug markers."""
    nested, edits, bug = [], 0, False
    last_text = ""
    try:
        with path.open("r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") != "assistant":
                    continue
                msg = o.get("message") or {}
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") == "tool_use":
                        nm = str(blk.get("name", "")).lower()
                        if nm == "agent":
                            inp = blk.get("input") or {}
                            d = (inp.get("description") or "").strip()[:60]
                            if d:
                                nested.append(d)
                        elif nm in EDIT_TOOLS:
                            edits += 1
                    elif blk.get("type") == "text":
                        last_text = str(blk.get("text", ""))
    except OSError:
        pass
    low = last_text.lower()
    if any(mk in low for mk in BUG_MARKERS):
        bug = True
    return {"nested": nested, "edits": edits, "bug": bug}


def do_stop(payload: dict) -> None:
    if payload.get("stop_hook_active"):
        return
    cwd = payload.get("cwd") or ""
    if not cwd:
        return
    board = find_board(Path(cwd))
    if board is None:
        return
    entry = queue_pop(board)
    if entry is None or entry.get("skip"):
        # No working card to close (read-only subagent, add-failure, or an
        # orphaned stop). Silent — never invent a card.
        return
    num = entry.get("card")
    if not num:
        return

    transcript = payload.get("transcript_path") or ""
    act = (scan_subagent_transcript(Path(transcript))
           if transcript else {"nested": [], "edits": 0, "bug": False})

    stype = entry.get("type", "subagent")
    desc = entry.get("desc", "")
    parts = [f"Subagent ({stype}) completed: {desc}."]
    if act["edits"]:
        parts.append(f"Made {act['edits']} file edit(s).")
    if act["nested"]:
        parts.append("Spawned nested subagent(s): " + "; ".join(act["nested"][:6]) + ".")
    if act["bug"]:
        parts.append("WARN output contained an explicit bug/traceback marker — "
                     "review and file a bug card if real.")
    parts.append("(Auto-carded by SubagentStop hook; FIFO-correlated — verify "
                 "pairing if subagents ran in parallel.)")
    writeup = " ".join(parts)

    fly_args = ["fly", num, "done", "--writeup", writeup, "--pause-ms", "120"]
    if act["nested"]:
        fly_args[5:5] = ["--subtask",
                         f"{len(act['nested'])} nested subagent(s)"]
    run_card(board, fly_args)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        if mode == "spawn":
            do_spawn(payload)
        elif mode == "stop":
            do_stop(payload)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
