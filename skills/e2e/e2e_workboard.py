#!/usr/bin/env python3
"""e2e_workboard.py — reusable end-to-end test harness for board-steward.

Codifies the verification patterns proven during ARCH REDESIGN v2 (multi-board
routing + reconciliation) so future overhauls reuse the harness instead of
re-deriving throwaway test scripts each time.

THE CARDINAL RULE (every test obeys it):
  NEVER pollute the user's live board or global state.
  - State is isolated via env overrides: BOARD_REGISTRY / BOARD_ASSIGNMENTS /
    BOARD_ACTIVE point at temp files; BOARD_NO_SERVER forces direct file writes
    for tests that don't need a server.
  - Boards under test are throwaway temp dirs seeded from templates/board.json.
  - The live board (default :7891) card count is captured before the run and
    asserted UNCHANGED after — a regression that touches it fails the suite.
  - Everything temp is torn down at the end.

USAGE
  python3 e2e_workboard.py multiboard     # multi-board routing/isolation (no LLM, free)
  python3 e2e_workboard.py recon          # recon flag + gating (no LLM, free)
  python3 e2e_workboard.py recon-haiku    # real Haiku recon E2E (costs ~1-2 Haiku calls)
  python3 e2e_workboard.py all            # multiboard + recon (free tier)
  python3 e2e_workboard.py all --haiku    # everything incl. the Haiku E2E

  BOARD_REPO=/path/to/WorkBoard  overrides the repo (default ~/Desktop/WorkBoard)

EXTENDING (for the NEXT overhaul)
  Add a function `def test_<group>_<name>(ctx): ...` that uses ctx.board(),
  ctx.isolate(), ctx.assert_eq(...). Register it in GROUPS. Keep the cardinal
  rule: isolate state, use throwaway boards, never touch the live board.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(os.environ.get("BOARD_REPO", str(Path.home() / "Desktop" / "WorkBoard")))
SCRIPTS = REPO / "scripts"
TEMPLATE = REPO / "templates" / "board.json"
CARD_PY = SCRIPTS / "card.py"
LIVE_HEALTH = "http://127.0.0.1:7891/health"


# ───────────────────────── test framework ─────────────────────────

class Ctx:
    """Per-run context: tmp dirs, isolated env, pass/fail tally, cleanup."""

    def __init__(self):
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self._tmp: list[str] = []
        self._state = tempfile.mkdtemp(prefix="e2e-state-")
        self._tmp.append(self._state)
        # Isolate ALL cross-board state into temp files (never touch ~/.board-steward).
        os.environ["BOARD_REGISTRY"] = f"{self._state}/registry.json"
        os.environ["BOARD_ASSIGNMENTS"] = f"{self._state}/assignments.json"
        os.environ["BOARD_ACTIVE"] = f"{self._state}/last-active"
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))

    def board(self, cards: list[dict] | None = None, *, from_template: bool = False) -> Path:
        """Make a throwaway project with a board.json; return the board.json path."""
        proj = tempfile.mkdtemp(prefix="e2e-proj-")
        self._tmp.append(proj)
        bdir = Path(proj) / "board"
        bdir.mkdir()
        bj = bdir / "board.json"
        if from_template and TEMPLATE.exists():
            shutil.copy(TEMPLATE, bj)
            if cards is not None:
                d = json.loads(bj.read_text()); d["cards"] = cards
                bj.write_text(json.dumps(d))
        else:
            bj.write_text(json.dumps({
                "rev": 1, "nextNum": 99, "activeWorkId": None,
                "columns": [{"id": c, "name": c} for c in
                            ("task", "backlog", "inprogress", "done", "mandatory", "notes")],
                "cards": cards or [],
            }))
        return bj

    def card(self, num, column, title, *, tags=None, cid=None) -> dict:
        """A minimally-valid card dict (real cards always carry an `id`)."""
        return {"id": cid or f"c-{num}", "num": num, "column": column,
                "title": title, "tags": tags or [],
                "createdAt": datetime.now(timezone.utc).isoformat()}

    def assert_eq(self, name, got, want):
        if got == want:
            self.passed.append(name); print(f"  ✓ {name}")
        else:
            msg = f"got {got!r}, want {want!r}"
            self.failed.append((name, msg)); print(f"  ✗ {name} — {msg}")

    def assert_true(self, name, cond, detail=""):
        self.assert_eq(name, bool(cond), True) if cond else \
            (self.failed.append((name, detail)), print(f"  ✗ {name} — {detail}"))

    def cleanup(self):
        for d in self._tmp:
            shutil.rmtree(d, ignore_errors=True)


def live_board_cards() -> int | None:
    """Card count of the live :7891 board, or None if no server (both fine)."""
    try:
        import urllib.request
        with urllib.request.urlopen(LIVE_HEALTH, timeout=1) as r:
            return json.load(r).get("cards")
    except Exception:
        return None


# ───────────────────────── multi-board tests ─────────────────────────

def test_multiboard_routing_isolation(ctx: Ctx):
    """A card added from inside project A lands on A, never B; last-active tracks."""
    os.environ["BOARD_NO_SERVER"] = "1"  # direct file write, no server/probe
    A = ctx.board([]); B = ctx.board([])
    for bj, title in ((A, "card for A"), (B, "card for B")):
        subprocess.run([sys.executable, str(CARD_PY), "add", "--title", title,
                        "--column", "task"], cwd=str(bj.parent.parent),
                       capture_output=True, text=True, timeout=20)
    ta = [c["title"] for c in json.loads(A.read_text())["cards"]]
    tb = [c["title"] for c in json.loads(B.read_text())["cards"]]
    ctx.assert_eq("multiboard.routing: A isolated", ta, ["card for A"])
    ctx.assert_eq("multiboard.routing: B isolated", tb, ["card for B"])
    active = Path(os.environ["BOARD_ACTIVE"]).read_text().strip()
    ctx.assert_eq("multiboard.last-active = last mutated (B)",
                  Path(active).resolve(), B.parent.resolve())
    os.environ.pop("BOARD_NO_SERVER", None)


def test_multiboard_disambiguation(ctx: Ctx):
    """At $HOME the active board wins over a newer-mtime board; mtime is fallback."""
    import importlib, port_registry as pr; importlib.reload(pr)
    A = ctx.board([]); B = ctx.board([])
    abd, bbd = str(A.parent.resolve()), str(B.parent.resolve())
    json.dump({abd: 7950, bbd: 7951}, open(os.environ["BOARD_ASSIGNMENTS"], "w"))
    pr.set_active(bbd)                                   # B active
    time.sleep(0.05); os.utime(A, None)                 # A newer mtime

    def pick():
        a = pr.get_active()
        if a and (Path(a) / "board.json").exists():
            return str(Path(a) / "board.json")
        best = None
        for d in pr.assignments():
            bj = Path(d) / "board.json"
            if bj.exists():
                m = bj.stat().st_mtime
                if best is None or m > best[0]:
                    best = (m, str(bj))
        return best[1] if best else ""

    ctx.assert_eq("multiboard.disambiguation: active (B) wins over mtime",
                  Path(pick()).resolve(), B.resolve())
    os.remove(os.environ["BOARD_ACTIVE"])               # clear active → mtime fallback
    ctx.assert_eq("multiboard.disambiguation: mtime fallback (A)",
                  Path(pick()).resolve(), A.resolve())


# ───────────────────────── recon tests (free) ─────────────────────────

def test_recon_only_discovered_flag(ctx: Ctx):
    """only_discovered scopes candidates: True→tagged only, False→all non-done."""
    os.environ["CLAUDECODE"] = "1"  # no-Haiku path: writes recon_pending we can count
    import importlib, hourly_reconcile as HR; importlib.reload(HR)
    bj = ctx.board([ctx.card(1, "inprogress", "live (untagged)"),
                    ctx.card(2, "inprogress", "mined", tags=["discovered"])])
    pend = bj.parent / "recon_pending.json"

    def n_candidates(only_disc):
        if pend.exists(): pend.unlink()
        HR.reconcile_sweep(CARD_PY, bj, [], only_discovered=only_disc)
        return len(json.loads(pend.read_text())["candidates"]) if pend.exists() else 0

    ctx.assert_eq("recon.only_discovered=True → mined only", n_candidates(True), 1)
    ctx.assert_eq("recon.only_discovered=False → all non-done", n_candidates(False), 2)
    os.environ.pop("CLAUDECODE", None)


def test_recon_gates_short_circuit(ctx: Ctx):
    """--reconcile-only must NOT call Haiku when (A) no non-done cards or
    (B) no recorded project activity (throwaway proj has none)."""
    def run(bj):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "hourly_extractor.py"),
             "--project", str(bj.parent.parent), "--board", str(bj),
             "--reconcile-only"], capture_output=True, text=True, timeout=30).stderr

    bjA = ctx.board([ctx.card(1, "done", "shipped")])
    ctx.assert_true("recon.gateA: only-done → skip", "no non-done cards" in run(bjA),
                    "expected 'no non-done cards' skip")
    bjB = ctx.board([ctx.card(1, "inprogress", "wip")])
    ctx.assert_true("recon.gateB: no project activity → skip",
                    "no recorded project activity" in run(bjB),
                    "expected 'no recorded project activity' skip")


def test_recon_claudecode_path(ctx: Ctx):
    """CLAUDECODE=1 → prose recon_pending (no Haiku). The unset→Haiku side is the
    recon-haiku E2E. This proves the spawn's `env -u CLAUDECODE` is load-bearing."""
    os.environ["CLAUDECODE"] = "1"
    import importlib, hourly_reconcile as HR; importlib.reload(HR)
    bj = ctx.board([ctx.card(1, "inprogress", "wip", tags=["discovered"])])
    HR.reconcile_sweep(CARD_PY, bj, [], only_discovered=True)
    ctx.assert_true("recon.CLAUDECODE=1 writes recon_pending (no Haiku)",
                    (bj.parent / "recon_pending.json").exists(),
                    "recon_pending.json not written")
    os.environ.pop("CLAUDECODE", None)


# ───────────────────────── recon test (real Haiku, opt-in) ─────────────────────────

def test_recon_haiku_e2e(ctx: Ctx):
    """Real Haiku: a shipped In-Progress card → done; a skipped one → backlog.
    Costs ~1 Haiku call. Throwaway board, CLAUDECODE unset, direct write."""
    os.environ.pop("CLAUDECODE", None)
    os.environ["BOARD_NO_SERVER"] = "1"
    import importlib, hourly_reconcile as HR; importlib.reload(HR)
    bj = ctx.board([ctx.card(1, "inprogress", "Add rate-limit header", cid="c-rate-1"),
                    ctx.card(2, "inprogress", "Investigate websocket spike", cid="c-spike-2")])
    now = datetime.now(timezone.utc)
    events = [
        {"kind": "user_prompt", "ts": now - timedelta(hours=2), "text": "add the rate-limit header to the API"},
        {"kind": "git_commit", "ts": now - timedelta(hours=1), "text": "add rate-limit header to API responses", "meta": {"shaShort": "abc1234"}},
        {"kind": "user_prompt", "ts": now - timedelta(minutes=30), "text": "great, shipped the rate limiter, it's done and verified"},
        {"kind": "user_prompt", "ts": now - timedelta(minutes=20), "text": "actually let's skip the websocket spike investigation for now, nvm"},
    ]
    print("    (calling real Haiku — may take ~5-30s)", file=sys.stderr)
    HR.reconcile_sweep(CARD_PY, bj, events, only_discovered=False)
    cols = {c["num"]: c["column"] for c in json.loads(bj.read_text())["cards"]}
    ctx.assert_eq("recon.haiku: shipped IP → done", cols.get(1), "done")
    ctx.assert_eq("recon.haiku: skipped IP → backlog", cols.get(2), "backlog")
    os.environ.pop("BOARD_NO_SERVER", None)


# ───────────────────────── runner ─────────────────────────

GROUPS = {
    "multiboard": [test_multiboard_routing_isolation, test_multiboard_disambiguation],
    "recon": [test_recon_only_discovered_flag, test_recon_gates_short_circuit,
              test_recon_claudecode_path],
    "recon-haiku": [test_recon_haiku_e2e],
}


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    group = args[0] if args else "all"

    if not CARD_PY.exists():
        print(f"error: board-steward repo not found at {REPO} "
              f"(set BOARD_REPO)", file=sys.stderr)
        return 2

    selected: list = []
    if group == "all":
        selected = GROUPS["multiboard"] + GROUPS["recon"]
        if "--haiku" in flags:
            selected += GROUPS["recon-haiku"]
    elif group in GROUPS:
        selected = GROUPS[group]
    else:
        print(f"unknown group '{group}'. choose: {', '.join(GROUPS)}, all",
              file=sys.stderr)
        return 2

    live_before = live_board_cards()
    ctx = Ctx()
    print(f"\n=== board-steward e2e :: {group} "
          f"({'incl. ' if (group=='recon-haiku' or '--haiku' in flags) else 'no '}Haiku) ===")
    try:
        for fn in selected:
            print(f"\n• {fn.__name__}")
            try:
                fn(ctx)
            except Exception as e:  # a test that crashes is a failure, not a stop
                ctx.failed.append((fn.__name__, f"EXCEPTION: {e}"))
                print(f"  ✗ {fn.__name__} — EXCEPTION: {e}")
    finally:
        ctx.cleanup()

    # Cardinal rule: the live board must be untouched.
    live_after = live_board_cards()
    if live_before is not None:
        if live_after == live_before:
            print(f"\n  ✓ live board untouched ({live_before} cards before & after)")
        else:
            ctx.failed.append(("live-board-untouched",
                               f"{live_before} → {live_after} (POLLUTED!)"))
            print(f"\n  ✗ live board POLLUTED: {live_before} → {live_after}")

    print(f"\n=== {len(ctx.passed)} passed, {len(ctx.failed)} failed ===")
    for name, why in ctx.failed:
        print(f"  FAIL {name}: {why}")
    return 1 if ctx.failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
