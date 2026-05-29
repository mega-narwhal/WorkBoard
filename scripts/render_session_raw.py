#!/usr/bin/env python3
"""#252 RAW-DUMP — render a Claude Code JSONL transcript to VERBATIM markdown.

Replaces the hand-written, summarized conversation_raw_*.md (which drifted from
the CLAUDE.md "pure conversation text — no summaries" rule). This emits the
actual raw turns straight from the transcript: every user prompt in full, every
assistant message in full, and each tool call shown (Bash commands verbatim,
Edit/Write/Read as file markers) — so the card.py transition calls are preserved
in place for the training pipeline (#251).

Usage:
  render_session_raw.py                      # newest session for $PWD's project → stdout
  render_session_raw.py path/to/session.jsonl
  render_session_raw.py --append-daily       # append to ~/Desktop/conversation_history/
                                             #   conversation_verbatim_YYMMDD.md (dedup by sessionId)
  render_session_raw.py --with-results       # include truncated tool-result markers

Pure stdlib.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
HIST_DIR = Path.home() / "Desktop" / "conversation_history"


def newest_session_for_cwd() -> Path | None:
    """The most-recently-modified transcript for the project matching $PWD."""
    enc = str(Path.cwd().resolve()).replace("/", "-")
    proj = PROJECTS / enc
    if not proj.is_dir():
        return None
    sessions = sorted(proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return sessions[0] if sessions else None


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text" and b.get("text"))
    return ""


def _is_tool_result(content) -> bool:
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def _render_tool(b: dict) -> str:
    name = b.get("name", "?")
    inp = b.get("input") or {}
    if name == "Bash":
        cmd = inp.get("command", "")
        return "  $ " + cmd.replace("\n", "\n    ")
    for key in ("file_path", "path", "notebook_path", "pattern"):
        if key in inp:
            return f"  [{name}] {inp[key]}"
    # fall back to a compact one-liner of the first scalar arg
    for k, v in inp.items():
        if isinstance(v, (str, int, float)):
            return f"  [{name}] {k}={str(v)[:80]}"
    return f"  [{name}]"


def render(path: Path, with_results: bool = False) -> str:
    sid = path.stem
    lines = [f"<!-- session: {sid} -->"]
    for raw in path.open(errors="replace"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if d.get("isSidechain"):
            continue
        t = d.get("type")
        ts = (d.get("timestamp") or "")[11:16]   # HH:MM (UTC)
        msg = d.get("message", {}) if isinstance(d.get("message"), dict) else {}
        content = msg.get("content")

        if t == "user":
            if _is_tool_result(content):
                if with_results:
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            out = b.get("content")
                            s = out if isinstance(out, str) else json.dumps(out)[:200]
                            lines.append(f"    → result ({len(s)} chars): {s[:200]}")
                continue
            text = _text_of(content)
            if text.strip():
                lines += ["", f"[USER] {ts}", text]
        elif t == "assistant":
            text = _text_of(content)
            head = f"[CLAUDE] {ts}"
            block = [text] if text.strip() else []
            tools = []
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tools.append(_render_tool(b))
            if block or tools:
                lines += ["", head] + block + tools
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="render a JSONL transcript to verbatim markdown")
    ap.add_argument("jsonl", nargs="?", type=Path, help="transcript path (default: newest for $PWD)")
    ap.add_argument("--append-daily", action="store_true",
                    help="append to ~/Desktop/conversation_history/conversation_verbatim_YYMMDD.md")
    ap.add_argument("--with-results", action="store_true", help="include truncated tool-result markers")
    args = ap.parse_args()

    path = args.jsonl or newest_session_for_cwd()
    if not path or not path.is_file():
        sys.exit("error: no transcript found (pass a JSONL path explicitly)")

    body = render(path, with_results=args.with_results)

    if not args.append_daily:
        sys.stdout.write(body)
        return

    # YYMMDD from the transcript's first timestamp, else today via mtime.
    ymd = None
    for raw in path.open(errors="replace"):
        try:
            ts = json.loads(raw).get("timestamp", "")
        except json.JSONDecodeError:
            ts = ""
        if ts:
            ymd = ts[2:4] + ts[5:7] + ts[8:10]
            break
    if not ymd:
        import time
        ymd = time.strftime("%y%m%d", time.localtime(path.stat().st_mtime))

    HIST_DIR.mkdir(parents=True, exist_ok=True)
    dst = HIST_DIR / f"conversation_verbatim_{ymd}.md"
    marker = f"<!-- session: {path.stem} -->"
    header = f"# Verbatim conversation log — 20{ymd[:2]}-{ymd[2:4]}-{ymd[4:6]}\n"

    if not dst.exists():
        dst.write_text(header + body)
        print(f"wrote verbatim session {path.stem} → {dst}")
        return

    existing = dst.read_text(errors="replace")
    if marker in existing:
        # Idempotent re-render: replace this session's block (marker → next
        # session marker or EOF) so the file always reflects the full session.
        start = existing.index(marker)
        nxt = existing.find("<!-- session: ", start + len(marker))
        end = nxt if nxt != -1 else len(existing)
        updated = existing[:start] + body.lstrip("\n") + ("\n" + existing[end:].lstrip("\n") if nxt != -1 else "")
        dst.write_text(updated)
        print(f"re-rendered verbatim session {path.stem} → {dst.name} (replaced block)")
    else:
        with dst.open("a") as f:
            f.write("\n" + body)
        print(f"appended verbatim session {path.stem} → {dst}")


if __name__ == "__main__":
    main()
