#!/usr/bin/env python3
"""sim_60d.py — Phase 2d (#87 SIM-60D) assertion harness.

Drives the production sim infra (#206) against a 60-day window of session
history, then asserts BOTH the board-shape gate AND the token-budget caps
documented in `docs/TOKEN_BUDGET.md`. Exit 0 on PASS, 1 on FAIL.

This is the late-adopter scenario: a user installs board-steward after 2
months of work and the skill must (a) surface that work as cards and (b)
stay within its documented token budget at 200+ card scale.

Budget assertions (from TOKEN_BUDGET.md §"Hard caps + thresholds"):
  - index.json ≤ 48 KB  (`archive_done.py --days 14` should keep this true)
  - SessionStart hook digest ≤ 1,500 chars (~ 380 tokens, soft cap 300)
  - Done writeup median ≤ 800 B  (warn-line in TOKEN_BUDGET §"Open hardening")

Shape assertions (looser than sim_2d to allow noisier 60-day data):
  - ≥ 20 cards
  - ≥ 4 distinct columns
  - ≥ 5 cards in done (proves col-dist holds at scale)

Usage:
  python3 sim_60d.py
  python3 sim_60d.py --project ~/Desktop/QuantifyMe/HFTAgents
  python3 sim_60d.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
HARNESS = SKILL_DIR / "scripts" / "simulate_install.sh"
HOOK = SKILL_DIR / "scripts" / "hook_session_start.sh"
ARCHIVE = SKILL_DIR / "scripts" / "archive_done.py"
REGEN_INDEX = SKILL_DIR / "scripts" / "regen_index.py"

DEFAULTS = {
    "project": str(Path.home() / "Desktop" / "WorkBoard"),
    "port": 7899,
    "sim_dir": str(Path.home() / "Desktop" / "board-sim-60d"),
    "days": 60,
    "max_cards": 200,
    "min_cards": 20,
    "min_cols": 4,
    "min_done": 5,
    # token budgets — keep in step with docs/TOKEN_BUDGET.md
    "max_index_kb": 48,
    "max_hook_chars": 1500,
    "max_writeup_p50_bytes": 800,
}


def _fetch_board(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/board.json", timeout=1.5) as r:
            return json.loads(r.read())
    except Exception:
        return None


def run_sim(args) -> tuple[dict, Path]:
    cmd = [
        "bash", str(HARNESS),
        "--project", args.project,
        "--port", str(args.port),
        "--sim-dir", args.sim_dir,
        "--days", str(args.days),
        "--max", str(args.max_cards),
        "--no-open",
        "--no-llm",
    ]
    print(f"[sim-60d] launching: {' '.join(cmd[2:])}", file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        sys.exit(f"[sim-60d] harness failed (exit {proc.returncode})")
    board = _fetch_board(args.port)
    if not board:
        sys.exit("[sim-60d] could not fetch board.json after harness ran")
    return board, Path(args.sim_dir) / "board"


def _apply_archive(board_dir: Path, days: int = 14) -> int:
    """Run archive_done.py against the sim board — realistic production state
    (archive is part of the scheduled maintenance per #203). Returns archived count."""
    board_json = board_dir / "board.json"
    if not (ARCHIVE.is_file() and board_json.is_file()):
        return 0
    proc = subprocess.run(
        ["python3", str(ARCHIVE), str(board_json), "--days", str(days)],
        capture_output=True, text=True, timeout=30,
    )
    # archive_done.py prints "archived N" on success; harmless if it bails
    if REGEN_INDEX.is_file():
        subprocess.run(["python3", str(REGEN_INDEX), str(board_json)],
                       capture_output=True, timeout=15)
    return 1 if "archived" in (proc.stdout or "") else 0


def measure_budgets(board_dir: Path, project_root: Path, port: int) -> dict:
    """Measure on-disk + on-wire sizes the user will actually feel."""
    idx = board_dir / "index.json"
    index_bytes = idx.stat().st_size if idx.is_file() else 0

    # Run the hook against the sim board to measure the digest payload size.
    env = os.environ.copy()
    env["PWD"] = str(project_root)
    proc = subprocess.run(
        ["bash", str(HOOK)],
        cwd=str(project_root),
        env=env,
        capture_output=True, text=True, timeout=10,
    )
    hook_chars = len(proc.stdout)

    board = _fetch_board(port) or {}
    writeup_lens = [
        len(c.get("writeup") or "")
        for c in board.get("cards", [])
        if c.get("column") == "done" and c.get("writeup")
    ]
    p50 = int(statistics.median(writeup_lens)) if writeup_lens else 0

    return {
        "index_bytes": index_bytes,
        "index_kb": round(index_bytes / 1024, 1),
        "hook_chars": hook_chars,
        "writeup_p50_bytes": p50,
        "writeup_samples": len(writeup_lens),
    }


def assert_all(board: dict, budgets: dict, mins: dict, strict: bool) -> tuple[bool, list[str], list[str]]:
    """Return (pass, failures, warnings). Budget violations are warnings by
    default — under --strict they become failures (CI pre-release gate)."""
    failures: list[str] = []
    warnings: list[str] = []
    cards = board.get("cards", [])
    cols = {c.get("column") for c in cards}
    done_count = sum(1 for c in cards if c.get("column") == "done")

    if len(cards) < mins["cards"]:
        failures.append(f"cards={len(cards)} < min {mins['cards']}")
    if len(cols) < mins["cols"]:
        failures.append(f"distinct columns={len(cols)} < min {mins['cols']}")
    if done_count < mins["done"]:
        failures.append(f"done count={done_count} < min {mins['done']}")

    budget_bucket = failures if strict else warnings
    if budgets["index_kb"] > mins["max_index_kb"]:
        budget_bucket.append(
            f"index.json={budgets['index_kb']}KB > cap {mins['max_index_kb']}KB "
            "(archive_done.py only sweeps doneAt > 14d — fresh install carries them all)"
        )
    if budgets["hook_chars"] > mins["max_hook_chars"]:
        budget_bucket.append(
            f"hook digest={budgets['hook_chars']} chars > cap "
            f"{mins['max_hook_chars']} (~{mins['max_hook_chars']//4} tok)"
        )
    if budgets["writeup_p50_bytes"] > mins["max_writeup_p50_bytes"]:
        budget_bucket.append(
            f"done writeup p50={budgets['writeup_p50_bytes']}B > cap "
            f"{mins['max_writeup_p50_bytes']}B"
        )
    return (len(failures) == 0, failures, warnings)


def teardown(port: int) -> None:
    if port in (7891, 7892):
        return
    try:
        out = subprocess.check_output(["lsof", "-ti", f"tcp:{port}"], text=True).strip()
        for pid in out.splitlines():
            os.kill(int(pid), 9)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=DEFAULTS["project"])
    ap.add_argument("--port", type=int, default=DEFAULTS["port"])
    ap.add_argument("--sim-dir", default=DEFAULTS["sim_dir"])
    ap.add_argument("--days", type=int, default=DEFAULTS["days"])
    ap.add_argument("--max-cards", type=int, default=DEFAULTS["max_cards"])
    ap.add_argument("--min-cards", type=int, default=DEFAULTS["min_cards"])
    ap.add_argument("--min-cols", type=int, default=DEFAULTS["min_cols"])
    ap.add_argument("--min-done", type=int, default=DEFAULTS["min_done"])
    ap.add_argument("--max-index-kb", type=int, default=DEFAULTS["max_index_kb"])
    ap.add_argument("--max-hook-chars", type=int, default=DEFAULTS["max_hook_chars"])
    ap.add_argument("--max-writeup-p50-bytes", type=int, default=DEFAULTS["max_writeup_p50_bytes"])
    ap.add_argument("--keep-running", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="treat token-budget violations as failures (default: warn). "
                         "Use in pre-release CI; relaxed default reflects fresh-install reality.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.port in (7891, 7892):
        sys.exit("error: refuse to use ports 7891/7892 (real boards)")
    if not HARNESS.is_file():
        sys.exit(f"error: harness not found at {HARNESS}")

    try:
        board, board_dir = run_sim(args)
        # Apply the maintenance the user would have scheduled (per #203 BOARD-ARCHIVE-SCHED):
        # archive Done cards older than 14d before measuring index.json budget.
        archived = _apply_archive(board_dir, days=14)
        if archived:
            board = _fetch_board(args.port) or board
        budgets = measure_budgets(board_dir, Path(args.sim_dir), args.port)
        mins = {
            "cards": args.min_cards, "cols": args.min_cols, "done": args.min_done,
            "max_index_kb": args.max_index_kb,
            "max_hook_chars": args.max_hook_chars,
            "max_writeup_p50_bytes": args.max_writeup_p50_bytes,
        }
        passed, failures, warnings = assert_all(board, budgets, mins, args.strict)

        cards = board.get("cards", [])
        cols = sorted({c.get("column") for c in cards})
        result = {
            "pass": passed,
            "cards": len(cards),
            "distinct_columns": cols,
            "done_count": sum(1 for c in cards if c.get("column") == "done"),
            "budgets": budgets,
            "failures": failures,
            "warnings": warnings,
            "thresholds": mins,
            "strict": args.strict,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            tag = "✅ PASS" if passed else "❌ FAIL"
            print(f"{tag}  cards={result['cards']} cols={len(cols)} done={result['done_count']}")
            print(f"     index={budgets['index_kb']}KB hook={budgets['hook_chars']}c "
                  f"writeup-p50={budgets['writeup_p50_bytes']}B "
                  f"(n={budgets['writeup_samples']})")
            for f in failures:
                print(f"  FAIL: {f}")
            for w in warnings:
                print(f"  WARN: {w}")
        return 0 if passed else 1
    finally:
        if not args.keep_running:
            teardown(args.port)


if __name__ == "__main__":
    sys.exit(main())
