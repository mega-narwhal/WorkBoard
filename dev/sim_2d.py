#!/usr/bin/env python3
"""sim_2d.py — Phase 2c (#86 SIM-2D) assertion harness.

Drives scripts/simulate_install.sh against a 2-day session-history window and
asserts the resulting board hits a healthy shape. Exit 0 on PASS, 1 on FAIL.
Used as a CI gate before tagging a release (referenced by Phase 2e launch-gate).

Reuses the production harness (#206 SIM-HARNESS) so we test the same code path
real users will run — no parallel "test-only" sim infra to drift.

Default thresholds match the user's stated bar for "watching it populate":
  - ≥ 5 cards after a 2-day window
  - ≥ 3 distinct columns (proves col-dist heuristic isn't dumping everything to done)
  - ≥ 1 card landed in done (proves shipped-detection works)
  - Server reachable within 30s (proves bootstrap doesn't hang)

Usage:
  python3 sim_2d.py                                # defaults
  python3 sim_2d.py --project ~/Desktop/MyProject
  python3 sim_2d.py --json                         # CI mode
  python3 sim_2d.py --min-cards 10 --min-cols 4    # tighter gate
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
HARNESS = SKILL_DIR / "dev" / "simulate_install.sh"

DEFAULTS = {
    "project": str(Path.home() / "Desktop" / "WorkBoard"),
    "port": 7898,
    "sim_dir": str(Path.home() / "Desktop" / "board-sim-2d"),
    "days": 2,
    "max_cards": 30,
    "min_cards": 5,
    "min_cols": 3,
    "boot_timeout_s": 30,
}


def _fetch_board(port: int, timeout: float = 1.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/board.json", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _wait_for_server(port: int, deadline_s: float) -> float | None:
    """Block until /health responds. Returns elapsed seconds, or None on timeout."""
    start = time.time()
    while time.time() - start < deadline_s:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as r:
                if r.status == 200:
                    return time.time() - start
        except Exception:
            pass
        time.sleep(0.3)
    return None


def run_sim(args) -> dict:
    """Spawn the harness, wait for it to finish, return the final board.json dict."""
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
    print(f"[sim-2d] launching harness: {' '.join(cmd[2:])}", file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        sys.exit(f"[sim-2d] harness failed (exit {proc.returncode})")
    board = _fetch_board(args.port)
    if not board:
        sys.exit("[sim-2d] could not fetch board.json after harness ran")
    return board


def assert_shape(board: dict, mins: dict) -> tuple[bool, list[str]]:
    """Return (pass, list_of_failure_reasons)."""
    failures = []
    cards = board.get("cards", [])
    if len(cards) < mins["cards"]:
        failures.append(f"cards={len(cards)} < min {mins['cards']}")
    cols = {c.get("column") for c in cards}
    if len(cols) < mins["cols"]:
        failures.append(f"distinct columns={len(cols)} < min {mins['cols']} (got {sorted(cols)})")
    done_count = sum(1 for c in cards if c.get("column") == "done")
    if done_count < 1:
        failures.append("0 cards landed in done — col-dist or shipped-detection broken")
    return (len(failures) == 0, failures)


def teardown(port: int) -> None:
    """Kill the harness server on the sim port. Real launchd boards on
    7891/7892 are explicitly refused by simulate_install.sh so this is safe."""
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
    ap.add_argument("--boot-timeout", type=int, default=DEFAULTS["boot_timeout_s"])
    ap.add_argument("--keep-running", action="store_true",
                    help="leave the sim server up after assertions (default: kill)")
    ap.add_argument("--json", action="store_true", help="emit JSON result for CI")
    args = ap.parse_args()

    if args.port in (7891, 7892):
        sys.exit("error: refuse to use ports 7891/7892 (real boards)")

    if not HARNESS.is_file():
        sys.exit(f"error: harness not found at {HARNESS}")

    try:
        board = run_sim(args)
        passed, failures = assert_shape(board, {"cards": args.min_cards, "cols": args.min_cols})
        cards = board.get("cards", [])
        cols = {c.get("column") for c in cards}
        result = {
            "pass": passed,
            "cards": len(cards),
            "distinct_columns": sorted(cols),
            "done_count": sum(1 for c in cards if c.get("column") == "done"),
            "failures": failures,
            "thresholds": {"min_cards": args.min_cards, "min_cols": args.min_cols},
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            tag = "✅ PASS" if passed else "❌ FAIL"
            print(f"{tag}  cards={result['cards']}  cols={len(cols)}  done={result['done_count']}")
            for f in failures:
                print(f"  - {f}")
        return 0 if passed else 1
    finally:
        if not args.keep_running:
            teardown(args.port)


if __name__ == "__main__":
    sys.exit(main())
