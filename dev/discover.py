#!/usr/bin/env python3
"""discover.py — mine the user's Claude Code session history for card material.

NOT a card creator. This is a context summarizer: it walks
~/.claude/projects/*/<session>.jsonl, finds sessions whose cwd is at or
below the target project, and emits a compact JSON summary of each session
(first/last user prompt, files touched, ship/defer hints, timestamps).

Claude (the steward) reads this output, applies judgment, and issues the
actual `card.py add` calls. Keeping intelligence in Claude, plumbing in
this script — so a user can `discover.py | less` and audit what's fed in.

Also surfaces MEMORY.md content if found in standard locations.

Stdlib only.

Usage:
    discover.py                          # cwd, last 7 days
    discover.py --project /path/to/repo  # explicit
    discover.py --days 30
    discover.py --max-sessions 20
    discover.py --memory                 # also include MEMORY.md if present
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Heuristics — small, easy to read, easy to tune.
SHIP_RE   = re.compile(r"\b(shipped|deployed|merged|verified|done|fixed|works|live|landed)\b", re.I)
DEFER_RE  = re.compile(r"\b(later|next session|tomorrow|todo|deferred|pending|next time|defer|punt)\b", re.I)
BUG_RE    = re.compile(r"\b(bug|broken|crash|fail|error|wrong|regress|issue)\b", re.I)
DECIDE_RE = re.compile(r"\b(decide|decision|discuss|propose|consider|option|design|approach)\b", re.I)
URGENT_RE = re.compile(r"\b(urgent|critical|blocked|asap|p0|p1|emergency|broken)\b", re.I)

# Skip prompts that aren't real work asks (slash commands, greetings, tiny replies)
SKIP_RE = re.compile(r"^(yes|no|ok|okay|sure|hi|hello|thanks|y|n|/.*|<.*>)$", re.I)


def msg_text(o: dict) -> str:
    """Extract user-facing text from a JSONL turn (user or assistant)."""
    msg = o.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            if t == "text":
                parts.append(c.get("text", ""))
            elif t == "tool_use" and c.get("name"):
                # Light hint that a tool was invoked — names are useful signal.
                parts.append(f"[tool:{c['name']}]")
        return "\n".join(parts)
    return ""


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s = s.rstrip("Z") + "+00:00" if s.endswith("Z") else s
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except Exception:
        return None


def files_from_tool_use(o: dict) -> list[str]:
    """Pull file paths from Edit/Write/Read tool uses."""
    paths = []
    msg = o.get("message") or {}
    content = msg.get("content")
    if not isinstance(content, list):
        return paths
    for c in content:
        if not isinstance(c, dict) or c.get("type") != "tool_use":
            continue
        name = c.get("name", "")
        if name not in ("Edit", "Write", "Read", "NotebookEdit"):
            continue
        inp = c.get("input") or {}
        p = inp.get("file_path") or inp.get("notebook_path")
        if p:
            paths.append(p)
    return paths


def summarize_session(path: Path, project: Path, since: datetime | None) -> dict | None:
    """One-pass scan of a JSONL session. Return None if irrelevant."""
    first_ts = last_ts = None
    cwd = None
    first_user = ""
    last_user = ""
    files: set[str] = set()
    ship_hits: list[str] = []
    defer_hits: list[str] = []
    bug_hits: list[str] = []
    n_user = n_asst = 0

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
                ts = parse_ts(o.get("timestamp"))
                if ts:
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                if o.get("cwd") and cwd is None:
                    cwd = o["cwd"]
                tp = o.get("type")
                if tp == "user":
                    txt = msg_text(o).strip()
                    if not txt or SKIP_RE.match(txt):
                        continue
                    n_user += 1
                    if not first_user:
                        first_user = txt
                    last_user = txt
                elif tp == "assistant":
                    n_asst += 1
                    txt = msg_text(o)
                    for fp in files_from_tool_use(o):
                        files.add(fp)
                    # Look at first sentence of each assistant turn — that's where
                    # ship/defer claims tend to live.
                    head = txt.strip().split("\n", 1)[0][:200]
                    if SHIP_RE.search(head):
                        ship_hits.append(head)
                    if DEFER_RE.search(head):
                        defer_hits.append(head)
                    if BUG_RE.search(head) and not SHIP_RE.search(head):
                        bug_hits.append(head)
    except OSError:
        return None

    # Recency / scope filters
    if last_ts is None:
        return None
    if since and last_ts < since:
        return None
    if cwd and project:
        # Permissive scope match: include if cwd is at, inside, or a parent of
        # the project. Users often run `claude` from $HOME and reference files
        # by full path, so a strict `cwd ⊆ project` filter throws away most
        # real signal. The scope just biases recency-ranked results.
        cwd_p = Path(cwd).resolve()
        proj_p = project.resolve()
        related = (
            cwd_p == proj_p
            or proj_p in cwd_p.parents
            or cwd_p in proj_p.parents
        )
        # Also keep sessions that EDITED files inside the project, regardless of cwd
        touched_project = any(
            Path(fp).resolve().is_relative_to(proj_p) if hasattr(Path, "is_relative_to") else str(Path(fp).resolve()).startswith(str(proj_p))
            for fp in files
        )
        if not (related or touched_project):
            return None
    if not first_user and not files:
        return None  # nothing actionable

    # Trim files to project-relative + cap
    proj_files = []
    for fp in sorted(files):
        try:
            rel = str(Path(fp).resolve().relative_to(project.resolve()))
            proj_files.append(rel)
        except (ValueError, OSError):
            pass
    proj_files = proj_files[:15]

    return {
        "sessionId": path.stem,
        "startedAt": first_ts.isoformat() if first_ts else None,
        "endedAt": last_ts.isoformat() if last_ts else None,
        "durationMin": round(((last_ts - first_ts).total_seconds() / 60), 1) if first_ts and last_ts else 0,
        "cwd": cwd,
        "turns": {"user": n_user, "assistant": n_asst},
        "firstUserPrompt": (first_user or "").strip()[:300],
        "lastUserPrompt":  (last_user or "").strip()[:300],
        "filesEdited": proj_files,
        "shipHints":  ship_hits[:5],
        "deferHints": defer_hits[:5],
        "bugHints":   bug_hits[:3],
    }


def find_sessions() -> list[Path]:
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir():
        return []
    return sorted(root.glob("*/*.jsonl"))


def find_memory(project: Path) -> Path | None:
    """Look for the project's MEMORY.md. Tries standard locations."""
    candidates = [
        # Per-project Claude Code memory
        Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(project.resolve())) / "memory" / "MEMORY.md",
        # User-wide
        Path.home() / ".claude" / "projects" / "-Users-malco" / "memory" / "MEMORY.md",
        # Project-checked-in
        project / "MEMORY.md",
        project / ".claude" / "MEMORY.md",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, default=Path.cwd())
    ap.add_argument("--days", type=int, default=7,
                    help="only sessions touched within the last N days (default 7)")
    ap.add_argument("--max-sessions", type=int, default=40)
    ap.add_argument("--memory", action="store_true",
                    help="also include MEMORY.md content in output")
    ap.add_argument("--all-projects", action="store_true",
                    help="don't filter sessions by cwd matching --project")
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days) if args.days > 0 else None
    project = args.project.resolve() if not args.all_projects else None

    sessions = []
    for p in find_sessions():
        s = summarize_session(p, project or args.project, since)
        if s:
            sessions.append(s)
    sessions.sort(key=lambda s: s.get("endedAt") or "", reverse=True)
    sessions = sessions[: args.max_sessions]

    out: dict = {
        "project": str(project) if project else None,
        "windowDays": args.days,
        "sessionCount": len(sessions),
        "sessions": sessions,
    }

    if args.memory:
        mem = find_memory(args.project)
        if mem:
            out["memory"] = {
                "path": str(mem),
                "content": mem.read_text(errors="replace"),
            }

    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
