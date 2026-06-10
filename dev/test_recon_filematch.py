#!/usr/bin/env python3
"""Empirical test for #350 — file-overlap + duplicate-of-done reconciliation
(hourly_reconcile). Real Haiku.

Builds a board + activity where the CORRECT answer is unambiguous, and asserts
the enriched reconcile (commit file-lists in the digest + done-card dedup) now
resolves it — where the OLD digest (subject-only, no files, no done cards) can't.

Scenarios on one board:
  #1 IN-PROGRESS, notes name board.html drag work; a COMMIT touched
     templates/board.html → MUST move to DONE (file overlap).
  #3 TASK, same unit as DONE #2 (calendar redesign) → MUST move to DONE
     (duplicate-of-done).
  #4 IN-PROGRESS investigation with NO matching commit → MUST STAY (control:
     the fix must not over-close genuinely-open work).

Set BOARD_SCRIPTS_DIR to point at a different tree (pre-fix, for contrast).
"""
import json, os, sys, importlib, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

os.environ.pop("CLAUDECODE", None)          # autonomous (Haiku) reconcile path
SCRIPTS = Path(os.environ.get("BOARD_SCRIPTS_DIR")
               or Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, str(SCRIPTS))
r = importlib.import_module("hourly_reconcile")


def main():
    print(f"#350 — file-overlap + dup-of-done reconcile test (scripts={SCRIPTS})")
    td = Path(tempfile.mkdtemp(prefix="recon350-"))
    bdir = td / "board"; bdir.mkdir()
    board = bdir / "board.json"
    board.write_text(json.dumps({
        "rev": 1, "nextNum": 5,
        "columns": ["task", "backlog", "inprogress", "done", "super-urgent"],
        "cards": [
            # #1: only the FILE reveals the match — the commit subject is vague.
            {"num": 1, "id": "c-1", "column": "inprogress",
             "title": "Tune extraction chunk-size handling",
             "notes": "Edited scripts/hourly_extractor.py chunk logic; no commit yet.",
             "tags": [], "history": []},
            # #2/#3: dup-of-done with NO commit — only the done card reveals #3.
            {"num": 2, "id": "c-2", "column": "done",
             "title": "Calendar day-separator redesign (per-column day grouping)",
             "notes": "Shipped the calendar day-separators.", "tags": [], "history": []},
            {"num": 3, "id": "c-3", "column": "task",
             "title": "Add per-column day separators to the calendar view",
             "notes": "Calendar day-separator work.", "tags": [], "history": []},
            # #4 control: genuinely open, no commit, no twin.
            {"num": 4, "id": "c-4", "column": "inprogress",
             "title": "Investigate intermittent prod timeout on the feed box",
             "notes": "Root cause unknown; still digging.", "tags": [], "history": []},
        ],
    }))

    now = datetime.now(timezone.utc)
    def ev(mins, kind, text, files=None, sha=None):
        e = {"ts": now - timedelta(minutes=mins), "source": "git" if kind == "git_commit" else "jsonl",
             "kind": kind, "text": text, "files": files or [], "meta": {}}
        if sha:
            e["meta"] = {"sha": sha, "shaShort": sha[:7]}
        return e
    events = [
        ev(40, "user_prompt", "the extraction is splitting things weirdly, tune the chunking"),
        ev(35, "asst_msg", "editing", files=["scripts/hourly_extractor.py"]),
        # VAGUE subject — only the [files: …] reveals this is #1's work.
        ev(30, "git_commit", "wip: misc cleanup",
           files=["scripts/hourly_extractor.py"], sha="abc1234deadbeef"),
        # NOTE: NO commit for the calendar work — #3 can only be caught via the
        # already-DONE #2 (duplicate-of-done), not via any ship signal.
    ]

    card_py = SCRIPTS / "card.py"
    r.reconcile_sweep(card_py, board, events, only_discovered=False)

    final = {c["num"]: c["column"] for c in json.loads(board.read_text())["cards"]}
    checks = {
        "#1 IP→done via FILE overlap (board.html commit)": final.get(1) == "done",
        "#3 task→done as DUPLICATE-OF-DONE (#2)":           final.get(3) == "done",
        "#4 control: no matching commit → STAYS inprogress": final.get(4) == "inprogress",
    }
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}  (final cols: {final})")
    ok = all(checks.values())
    print(f"\n{sum(checks.values())}/{len(checks)} passed")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
