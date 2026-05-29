#!/usr/bin/env python3
"""#251 TRAIN-EXTRACT — mine Claude Code JSONL transcripts into a training set
for the lifecycle-transition prediction model, and archive the raw transcripts
before Claude Code rotates them.

The TRUE raw conversation lives in ~/.claude/projects/<proj>/<sessionId>.jsonl
(NOT the summarized conversation_raw_*.md). Each transcript is an ordered log of
verbatim user prompts, assistant text, and tool_use calls — including the
`card.py add/move/fly/bug/improve/subtask` calls that ARE the transition labels.

Outputs (under --out, default WorkBoard/training_data/, gitignored):
  raw_transcripts/<proj>__<sessionId>.jsonl   verbatim archive copy (durable)
  sessions/<sessionId>.events.jsonl            ordered event stream per session
  transitions.jsonl                            flat (context -> label) examples

Usage:
  extract_transitions.py                 # mine ~/.claude/projects, write dataset
  extract_transitions.py --context 6     # 6 preceding turns of context per example
  extract_transitions.py --no-archive    # skip the raw copy
  extract_transitions.py --keep-tmp      # include /tmp smoke-test card.py calls

Pure stdlib.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

DEFAULT_PROJECTS = Path.home() / ".claude" / "projects"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "training_data"

# card.py invoked directly (path or bare) or via a $CARD / $C shell var.
_VERB = r"(add|move|fly|bug|improve|subtask)"
_CARD_PATTERNS = [
    re.compile(r"card\.py\s+" + _VERB + r"\b"),
    re.compile(r"\$\{?CARD\}?\s+" + _VERB + r"\b"),
    re.compile(r"\$\{?C\}?\s+" + _VERB + r"\b"),
]
# column keywords used to derive the move/fly target label
_COL_LABEL = {
    "inprogress": "IN_PROGRESS", "done": "DONE", "backlog": "BACKLOG",
    "task": "TASK", "ideas": "IDEAS", "blocked": "BLOCKED", "notes": "NOTES",
    "mandatory": "MANDATORY",
}


def iter_transcripts(projects_dir: Path):
    """Yield (project_name, jsonl_path) for every session transcript."""
    if not projects_dir.is_dir():
        return
    for proj in sorted(projects_dir.iterdir()):
        if not proj.is_dir():
            continue
        for f in sorted(proj.glob("*.jsonl")):
            yield proj.name, f


def _text_of(content) -> str:
    """Verbatim text of a message.content (str or block-list). '' if none."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def _is_tool_result(content) -> bool:
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def _card_calls_in(cmd: str):
    """Extract every card.py transition from one Bash command string.
    Returns list of dicts {verb, label, target, ref, raw, is_tmp}."""
    if not cmd:
        return []
    out = []
    for pat in _CARD_PATTERNS:
        for m in pat.finditer(cmd):
            verb = m.group(1)
            tail = cmd[m.end():m.end() + 120]      # the args right after the verb
            ref = None
            mref = re.search(r"\b(\d+|c-[\w-]+|s-[\w-]+)\b", tail)
            if mref:
                ref = mref.group(1)
            label, target = _label_for(verb, cmd, tail)
            out.append({
                "verb": verb, "label": label, "target": target, "ref": ref,
                "raw": cmd[m.start():m.end() + 80].strip(),
                "is_tmp": "/tmp/" in cmd or "smoke" in cmd.lower(),
            })
    return out


def _label_for(verb, cmd, tail):
    if verb == "add":
        mcol = re.search(r"--column\s+(\S+)", cmd)
        col = mcol.group(1) if mcol else ("ideas" if "--auto" in cmd else "task")
        return f"CREATE_{_COL_LABEL.get(col, col.upper())}", col
    if verb in ("move", "fly"):
        # target column is the first column keyword after the ref
        mcol = re.search(r"\b(" + "|".join(_COL_LABEL) + r")\b", tail)
        col = mcol.group(1) if mcol else None
        return (_COL_LABEL.get(col, "MOVE") if col else "MOVE"), col
    if verb == "bug":
        return "BUGGED", None
    if verb == "improve":
        return "IMPROVE", None
    if verb == "subtask":
        mop = re.search(r"subtask\s+(add|done|rm)", cmd)
        return f"SUBTASK_{(mop.group(1) if mop else 'op').upper()}", None
    return verb.upper(), None


def parse_session(path: Path):
    """Return an ordered event list for one transcript.
    Events: {seq, ts, kind: user|assistant|transition, text?, ...transition fields}."""
    events = []
    seq = 0
    for line in path.open(errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("isSidechain"):          # subagent thread — not the main convo
            continue
        t = d.get("type")
        ts = d.get("timestamp", "")
        msg = d.get("message", {}) if isinstance(d.get("message"), dict) else {}
        content = msg.get("content")

        if t == "user":
            if _is_tool_result(content):
                continue                  # tool output, not a human turn
            text = _text_of(content)
            if text.strip():
                events.append({"seq": seq, "ts": ts, "kind": "user", "text": text})
                seq += 1
        elif t == "assistant":
            text = _text_of(content)
            if text.strip():
                events.append({"seq": seq, "ts": ts, "kind": "assistant", "text": text})
                seq += 1
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use" \
                            and b.get("name") == "Bash":
                        cmd = (b.get("input") or {}).get("command", "")
                        for call in _card_calls_in(cmd):
                            events.append({"seq": seq, "ts": ts, "kind": "transition", **call})
                            seq += 1
    return events


def main():
    ap = argparse.ArgumentParser(description="mine JSONL transcripts → transition training set")
    ap.add_argument("--projects", type=Path, default=DEFAULT_PROJECTS,
                    help="Claude Code projects dir (default ~/.claude/projects)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="output dir (default WorkBoard/training_data)")
    ap.add_argument("--context", type=int, default=4,
                    help="preceding conversation turns of context per example")
    ap.add_argument("--no-archive", action="store_true", help="skip raw transcript copy")
    ap.add_argument("--keep-tmp", action="store_true",
                    help="include /tmp smoke-test card.py calls (default: excluded)")
    args = ap.parse_args()

    out = args.out
    (out / "raw_transcripts").mkdir(parents=True, exist_ok=True)
    (out / "sessions").mkdir(parents=True, exist_ok=True)

    n_sessions = n_turns = n_trans = n_examples = n_tmp = 0
    label_counts = {}
    flat = (out / "transitions.jsonl").open("w")

    for proj, path in iter_transcripts(args.projects):
        sid = path.stem
        events = parse_session(path)
        if not events:
            continue
        n_sessions += 1

        if not args.no_archive:
            dst = out / "raw_transcripts" / f"{proj}__{sid}.jsonl"
            try:
                if not dst.exists() or dst.stat().st_size != path.stat().st_size:
                    shutil.copy2(path, dst)
            except OSError:
                pass

        with (out / "sessions" / f"{sid}.events.jsonl").open("w") as sf:
            for e in events:
                sf.write(json.dumps(e, ensure_ascii=False) + "\n")

        # flat (context -> label) examples, one per transition
        turns = [e for e in events if e["kind"] in ("user", "assistant")]
        n_turns += len(turns)
        for i, e in enumerate(events):
            if e["kind"] != "transition":
                continue
            n_trans += 1
            if e.get("is_tmp"):
                n_tmp += 1
                if not args.keep_tmp:
                    continue
            ctx = [t for t in events[:i] if t["kind"] in ("user", "assistant")][-args.context:]
            flat.write(json.dumps({
                "session": sid, "project": proj, "ts": e["ts"],
                "label": e["label"], "verb": e["verb"], "target": e.get("target"),
                "card_ref": e.get("ref"), "cmd": e.get("raw"), "is_tmp": e.get("is_tmp", False),
                "context": [{"role": c["kind"], "text": c["text"]} for c in ctx],
            }, ensure_ascii=False) + "\n")
            n_examples += 1
            label_counts[e["label"]] = label_counts.get(e["label"], 0) + 1
    flat.close()

    print(f"sessions parsed : {n_sessions}")
    print(f"conversation turns: {n_turns}")
    print(f"transitions found : {n_trans}  ({n_tmp} were /tmp smoke calls"
          f"{' — INCLUDED' if args.keep_tmp else ' — excluded'})")
    print(f"training examples : {n_examples}")
    if label_counts:
        print("label breakdown:")
        for lbl, c in sorted(label_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {lbl:<18} {c}")
    print(f"\nwrote → {out}/  (transitions.jsonl, sessions/, raw_transcripts/)")


if __name__ == "__main__":
    main()
