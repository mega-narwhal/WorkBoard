#!/usr/bin/env python3
"""#644 — fill the three test gaps flagged in review F5:

  E1  #384 GATE-REOPEN-ON-EXCEPTION: if the end-of-replay reconcile_sweep RAISES,
      run()'s try/finally must still flip the replay gate back open (else every
      future SessionStart recon stands down forever). Driven through real run()
      with a reconcile_sweep that throws.
  E2  recon_lock CONTENTION: while one pass holds recon_lock, a second acquisition
      yields False (non-blocking) — and the lock is reacquirable once released.
  E3  _SEC_PER_CHUNK ESTIMATE MODEL: estimate_fill's eta math is
      ceil(chunks / workers) * _SEC_PER_CHUNK, with buckets/chunks counted from
      the bucketizer.

Run:  python3 dev/test_644_gate_locks_estimate.py  →  exit 0 = green, 1 = a fail.
LLM-free, live-board-free (throwaway boards; harvest/extract/recon seams patched).
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import hourly_extractor as H  # noqa: E402
import _boardio               # noqa: E402

_fails = 0


def check(cond: bool, msg: str) -> None:
    global _fails
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        _fails += 1


# ── E1: the gate reopens even when the end-of-replay reconcile raises ─────────
def test_gate_reopens_on_reconcile_exception():
    print("E1 (#384): reconcile_sweep raises → gate STILL reopens")
    saved = {n: getattr(H, n) for n in
             ("_anchor_offset_days", "_run_window", "_flatten_events",
              "_filter_events", "reconcile_sweep")}
    H._anchor_offset_days = lambda *a, **k: 0
    H._run_window = lambda *a, **k: (0, [])          # no harvest / no emit
    H._flatten_events = lambda *a, **k: [{"ts": datetime.now(timezone.utc)}]
    H._filter_events = lambda events, *a, **k: events  # non-empty → recon runs
    def _boom(*a, **k):
        raise RuntimeError("simulated reconcile failure")
    H.reconcile_sweep = _boom
    try:
        with tempfile.TemporaryDirectory() as d:
            board = Path(d) / "board.json"
            board.write_text("{}")
            raised = False
            try:
                H.run(Path("/tmp/wb644-proj"), board, port=0, days=1,
                      show_lifecycle=False, pace_s=0.0, max_buckets=0,
                      tier_fly=True, mode="haiku", reconcile=True)
            except RuntimeError:
                raised = True   # the sweep's exception propagates (after finally)
            check(raised, "reconcile exception propagates out of run()")
            check(H._replay_complete(board) is True,
                  "gate REOPENED despite the exception (#384 not stuck)")
            st = json.loads(H._replay_state_path(board).read_text())
            check(st.get("completed_card_replay") == 1,
                  "completed_card_replay flipped to 1 in finally")
    finally:
        for n, v in saved.items():
            setattr(H, n, v)


# ── E2: recon_lock is non-blocking and reacquirable ──────────────────────────
def test_recon_lock_contention():
    print("E2: recon_lock contention (non-blocking) + release")
    with tempfile.TemporaryDirectory() as d:
        board = Path(d) / "board.json"
        board.write_text("{}")
        with _boardio.recon_lock(board) as a:
            check(a is True, "first acquisition succeeds")
            with _boardio.recon_lock(board) as b:
                check(b is False, "second concurrent acquisition → False (no wait)")
        # outer released → reacquirable
        with _boardio.recon_lock(board) as c:
            check(c is True, "lock reacquirable after release")


# ── E3: estimate_fill eta math = ceil(chunks/workers) * _SEC_PER_CHUNK ────────
def test_estimate_model():
    print("E3: _SEC_PER_CHUNK estimate model")
    # 5 events in 5 distinct hour buckets → 5 buckets; chunk_size=1 → 5 chunks.
    base = H._bucket_hour(datetime.now(timezone.utc), 60)
    events = [{"ts": datetime.fromtimestamp((base - i) * 3600 + 60,
                                            tz=timezone.utc)}
              for i in range(5)]
    saved = {n: getattr(H, n) for n in
             ("_anchor_offset_days", "_flatten_events", "_filter_events")}
    H._anchor_offset_days = lambda *a, **k: 0
    H._flatten_events = lambda *a, **k: list(events)
    H._filter_events = lambda evs, *a, **k: evs
    try:
        for workers in (1, 2, 8):
            est = H.estimate_fill(Path("/tmp/wb644-proj"), days=2, bucket_min=60,
                                  chunk_size=1, workers=workers, sources=None)
            expected = math.ceil(5 / workers) * H._SEC_PER_CHUNK
            check(est["buckets"] == 5, f"workers={workers}: 5 buckets counted")
            check(est["chunks"] == 5, f"workers={workers}: 5 chunks (chunk_size=1)")
            check(est["eta_sec"] == int(expected),
                  f"workers={workers}: eta_sec={est['eta_sec']} == "
                  f"ceil(5/{workers})*{H._SEC_PER_CHUNK}={int(expected)}")
            check(est["eta_min"] == round(expected / 60.0, 1),
                  f"workers={workers}: eta_min derived from eta_sec")
    finally:
        for n, v in saved.items():
            setattr(H, n, v)


if __name__ == "__main__":
    test_gate_reopens_on_reconcile_exception()
    test_recon_lock_contention()
    test_estimate_model()
    print()
    if _fails:
        print(f"✗ {_fails} check(s) FAILED")
        sys.exit(1)
    print("✓ all #644 checks passed")
