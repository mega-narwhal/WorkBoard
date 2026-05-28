#!/usr/bin/env python3
"""discover2.py — time-bucketed cross-source work extractor.

Replaces discover.py. Three bug fixes + one structural change:
  bug 1: filesEdited filter — keep both raw and in-project so ship gate
         doesn't lose signal when a session edits notes/plans/sibling repos.
  bug 2: SKIP_RE undercount — count user turns BEFORE classifying them, so
         short replies don't vanish from the turn total.
  bug 3: SHIP_RE false positives — require either a strong word
         (shipped|deployed|merged|landed|verified) OR a weak word with a
         file edit in the same 60s window. Sentence-final 'Done.' subsection
         closers no longer count.

Structural: output is task-shaped, not session-shaped. A bucket is 10 minutes
(configurable). Within a bucket, substantive prompts seed tasks; short / marker /
fast-follow prompts merge. Pass 2 walks the task list once more and stitches
adjacent fragments sharing files into one card.

Sources harvested (all silent, no user prompts on default install):
  ~/.claude/projects/*/*.jsonl                       — session turns + tool_use
  ~/.claude/projects/-Users-malco/memory/*.md        — auto-memory mtime
  ~/Desktop/conversation_history/conversation_raw_*.md — manual dumps
  ~/.claude/plans/*.md                               — plan mtime
  git log on the project repo                        — commits with timestamps

Stdlib only.

Usage:
    discover2.py                          # cwd, last 7 days
    discover2.py --project /path/to/repo
    discover2.py --days 30 --bucket-min 10
    discover2.py --legacy                 # fall back to discover.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------- heuristics ----------
SHIP_STRONG_RE = re.compile(r"\b(shipped|deployed|merged|landed|verified)\b", re.I)
SHIP_WEAK_RE   = re.compile(r"\b(done|fixed|works|live)\b", re.I)
DEFER_RE       = re.compile(r"\b(later|next session|tomorrow|todo|deferred|pending|punt|defer)\b", re.I)
BUG_RE         = re.compile(r"\b(bug|broken|crash|fail|error|wrong|regress|issue)\b", re.I)
COMMIT_SHA_RE  = re.compile(r"\b[0-9a-f]{7,40}\b")
# `Done. Status:` / `Done.` / `Done:` at the START of a sentence/line are
# subsection closers, NOT ship claims. Reject if SHIP_WEAK_RE matched there.
DONE_CLOSER_RE = re.compile(r"^\s*Done\s*[.:]", re.I)

# Tiny replies that aren't real work asks. Used to CLASSIFY prompts, NOT to
# drop them from turn counts.
TRIVIAL_RE = re.compile(r"^(yes|no|ok|okay|sure|hi|hello|thanks|y|n|/.*|<.*>)$", re.I)

CONT_MARKERS = ("also", "actually", "wait", "oh", "btw", "see ", "hmm",
                "nvm", "fix", "revert", "and ", "but ", "still ")
CONT_SHORT_LEN  = 40
CONT_MAX_GAP_S  = 90
SPLIT_MIN_LEN   = 150
SPLIT_MIN_GAP_S = 300

# ---------- shared types ----------
# Event = (ts:datetime, source:str, kind:str, text:str, files:list[str], meta:dict)
# kind ∈ {"user_prompt", "asst_msg", "tool_use", "memory_write", "convo_user",
#         "convo_asst", "plan_write", "git_commit"}


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s = s.rstrip("Z") + "+00:00" if s.endswith("Z") else s
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except Exception:
        return None


def msg_text(o: dict) -> str:
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
        return "\n".join(parts)
    return ""


def files_from_tool_use(o: dict) -> list[tuple[str, str]]:
    """[(tool_name, path), ...] for file-touching tools."""
    out: list[tuple[str, str]] = []
    msg = o.get("message") or {}
    content = msg.get("content")
    if not isinstance(content, list):
        return out
    for c in content:
        if not isinstance(c, dict) or c.get("type") != "tool_use":
            continue
        name = c.get("name", "")
        if name not in ("Edit", "Write", "Read", "NotebookEdit", "MultiEdit"):
            continue
        inp = c.get("input") or {}
        p = inp.get("file_path") or inp.get("notebook_path")
        if p:
            out.append((name, p))
    return out


# ---------- sources ----------

def harvest_jsonl(since: datetime | None) -> list[dict]:
    """Walk ~/.claude/projects/*/*.jsonl. Yield one event per turn."""
    root = Path.home() / ".claude" / "projects"
    events: list[dict] = []
    if not root.is_dir():
        return events
    for jpath in sorted(root.glob("*/*.jsonl")):
        try:
            with jpath.open("r", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    ts = parse_ts(o.get("timestamp"))
                    if ts is None:
                        continue
                    if since and ts < since:
                        continue
                    cwd = o.get("cwd") or ""
                    tp = o.get("type")
                    if tp == "user":
                        txt = msg_text(o).strip()
                        if not txt:
                            continue
                        events.append({
                            "ts": ts, "source": "jsonl", "kind": "user_prompt",
                            "text": txt,
                            "files": [],
                            "meta": {"sessionId": jpath.stem, "cwd": cwd},
                        })
                    elif tp == "assistant":
                        txt = msg_text(o)
                        tu = files_from_tool_use(o)
                        events.append({
                            "ts": ts, "source": "jsonl", "kind": "asst_msg",
                            "text": txt[:2000],
                            "files": [p for _, p in tu],
                            "meta": {"sessionId": jpath.stem, "cwd": cwd,
                                     "tools": [n for n, _ in tu]},
                        })
        except OSError:
            continue
    return events


def harvest_memory(since: datetime | None) -> list[dict]:
    """memory/*.md files — mtime is the signal (no useful event timeline inside)."""
    out: list[dict] = []
    mem_dir = Path.home() / ".claude" / "projects" / "-Users-malco" / "memory"
    if not mem_dir.is_dir():
        return out
    for p in mem_dir.glob("*.md"):
        try:
            ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if since and ts < since:
            continue
        out.append({
            "ts": ts, "source": "memory", "kind": "memory_write",
            "text": p.name, "files": [str(p)], "meta": {},
        })
    return out


def harvest_plans(since: datetime | None) -> list[dict]:
    """plans/*.md — mtime signal."""
    out: list[dict] = []
    plan_dir = Path.home() / ".claude" / "plans"
    if not plan_dir.is_dir():
        return out
    for p in plan_dir.glob("*.md"):
        try:
            ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if since and ts < since:
            continue
        out.append({
            "ts": ts, "source": "plans", "kind": "plan_write",
            "text": p.name, "files": [str(p)], "meta": {},
        })
    return out


_CONVO_HEADER_RE = re.compile(r"^\[(USER|CLAUDE)\]\s+(\d{1,2}):(\d{2})", re.M)


def harvest_convo(since: datetime | None, convo_dir: Path | None = None) -> list[dict]:
    """conversation_raw_YYMMDD.md — parses [USER] HH:MM markers."""
    out: list[dict] = []
    convo_dir = convo_dir or (Path.home() / "Desktop" / "conversation_history")
    if not convo_dir.is_dir():
        return out
    for p in sorted(convo_dir.glob("conversation_raw_*.md")):
        m = re.search(r"conversation_raw_(\d{6})\.md$", p.name)
        if not m:
            continue
        try:
            date_part = datetime.strptime(m.group(1), "%y%m%d")
        except ValueError:
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        # Parse [USER] HH:MM and [CLAUDE] HH:MM markers, anchoring each marker
        # to a UTC ts so it can bucket like jsonl events. The HH:MM is local
        # time — we attach date_part + UTC to keep it timezone-stable.
        for hm in _CONVO_HEADER_RE.finditer(text):
            who, hh, mm = hm.group(1), int(hm.group(2)), int(hm.group(3))
            ts = date_part.replace(hour=hh, minute=mm, tzinfo=timezone.utc)
            if since and ts < since:
                continue
            # Grab the body up to the next header
            body_start = hm.end()
            nm = _CONVO_HEADER_RE.search(text, body_start)
            body = text[body_start:nm.start() if nm else None].strip()
            out.append({
                "ts": ts, "source": "convo",
                "kind": "convo_user" if who == "USER" else "convo_asst",
                "text": body[:2000], "files": [],
                "meta": {"file": str(p)},
            })
    return out


def harvest_git(project: Path, since: datetime | None) -> list[dict]:
    """git log --since=... in project — one event per commit."""
    out: list[dict] = []
    if not (project / ".git").is_dir():
        return out
    since_arg = since.strftime("%Y-%m-%d") if since else "30 days ago"
    try:
        proc = subprocess.run(
            ["git", "-C", str(project), "log",
             f"--since={since_arg}",
             "--pretty=format:%H|%cI|%s"],
            capture_output=True, text=True, timeout=8,
        )
        if proc.returncode != 0:
            return out
        for line in proc.stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            sha, iso, subj = parts
            ts = parse_ts(iso)
            if ts is None:
                continue
            if since and ts < since:
                continue
            out.append({
                "ts": ts, "source": "git", "kind": "git_commit",
                "text": subj, "files": [],
                "meta": {"sha": sha, "shaShort": sha[:7]},
            })
    except (OSError, subprocess.SubprocessError):
        pass
    return out


# ---------- bucketing + task extraction ----------

def bucket_id(ts: datetime, bucket_min: int) -> int:
    """floor(epoch / bucket_seconds)"""
    return int(ts.timestamp()) // (bucket_min * 60)


def is_trivial(text: str) -> bool:
    line = text.strip().split("\n", 1)[0]
    if TRIVIAL_RE.match(line):
        return True
    # Synthetic markers from interrupted turns aren't real prompts.
    if "[Request interrupted by user]" in line:
        return True
    return False


def is_continuation(prompt_text: str, prev_text: str, gap_s: float,
                    prompt_files: list[str], prev_files: list[str]) -> bool:
    """heuristic A continuation merge rules."""
    txt = prompt_text.strip()
    head = txt.lower()[:60]
    # Rule 1: short
    if len(txt) < CONT_SHORT_LEN:
        return True
    # Rule 2: continuation marker at start
    for m in CONT_MARKERS:
        if head.startswith(m):
            return True
    # Rule 3: fast-follow with no new file
    if gap_s <= CONT_MAX_GAP_S:
        new_files = set(prompt_files) - set(prev_files)
        if not new_files:
            return True
    return False


def should_split(prompt_text: str, prev_text: str, gap_s: float,
                 prompt_files: list[str], prev_files: list[str]) -> bool:
    """All three required for a forced split."""
    txt = prompt_text.strip()
    if len(txt) < SPLIT_MIN_LEN:
        new_files = set(prompt_files) - set(prev_files)
        if not new_files:
            return False
    if gap_s < SPLIT_MIN_GAP_S:
        return False
    head = txt.lower()[:60]
    for m in CONT_MARKERS:
        if head.startswith(m):
            return False
    return True


def files_in_window(events: list[dict], center_ts: datetime,
                    window_s: int = 60) -> list[str]:
    """Files edited within ±window_s of center_ts."""
    out: list[str] = []
    for e in events:
        if e["kind"] not in ("asst_msg", "tool_use"):
            continue
        if not e["files"]:
            continue
        dt = abs((e["ts"] - center_ts).total_seconds())
        if dt <= window_s:
            out.extend(e["files"])
    return out


def classify_ship(text: str, has_nearby_files: bool) -> str | None:
    """Return cleaned ship hit string or None. Bug 3 fix."""
    head = text.strip().split("\n", 1)[0][:200]
    # Reject 'Done.' subsection closers
    if DONE_CLOSER_RE.match(head):
        return None
    if SHIP_STRONG_RE.search(head):
        return head
    if SHIP_WEAK_RE.search(head) and has_nearby_files:
        return head
    if COMMIT_SHA_RE.search(head) and (SHIP_STRONG_RE.search(head) or has_nearby_files):
        return head
    return None


def extract_tasks(events: list[dict], bucket_min: int, project: Path) -> list[dict]:
    """Heuristic A — walk user_prompt events in time order, merge or split."""
    events.sort(key=lambda e: e["ts"])
    # Index assistant events by bucket → for files_in_window lookups
    user_events = [e for e in events
                   if e["kind"] in ("user_prompt", "convo_user")]

    tasks: list[dict] = []
    active: dict | None = None
    last_substantive_ts: datetime | None = None
    last_files: list[str] = []
    last_text: str = ""

    for ev in user_events:
        text = ev["text"].strip()
        if not text:
            continue
        trivial = is_trivial(text)
        gap_s = ((ev["ts"] - last_substantive_ts).total_seconds()
                 if last_substantive_ts else 1e9)
        # Look at file edits in ±90s around this prompt — they're "the work
        # being driven by this prompt".
        prompt_files = files_in_window(events, ev["ts"], window_s=120)

        if active is None:
            # Don't let a trivial reply seed the first task — wait for
            # a substantive prompt.
            if trivial:
                continue
            active = _start_task(ev, prompt_files)
            tasks.append(active)
            last_substantive_ts = ev["ts"]
            last_files = prompt_files
            last_text = text
            continue

        # Same bucket = same conversation thread. Different bucket = harder
        # threshold to keep streaming into one task.
        same_bucket = bucket_id(ev["ts"], bucket_min) == \
                      bucket_id(active["ts_start"], bucket_min)

        if trivial:
            _merge_into(active, ev, prompt_files)
            continue

        if same_bucket and is_continuation(text, last_text, gap_s,
                                           prompt_files, last_files):
            _merge_into(active, ev, prompt_files)
            last_substantive_ts = ev["ts"]
            last_files = prompt_files
            last_text = text
            continue

        # Force-split conditions met → start new task
        if should_split(text, last_text, gap_s, prompt_files, last_files):
            active = _start_task(ev, prompt_files)
            tasks.append(active)
            last_substantive_ts = ev["ts"]
            last_files = prompt_files
            last_text = text
            continue

        # Default: same bucket → merge, different bucket → split
        if same_bucket:
            _merge_into(active, ev, prompt_files)
            last_substantive_ts = ev["ts"]
            last_files = prompt_files
            last_text = text
        else:
            active = _start_task(ev, prompt_files)
            tasks.append(active)
            last_substantive_ts = ev["ts"]
            last_files = prompt_files
            last_text = text

    # Attach context (files, ships, bugs, commits, memory, plans) to tasks.
    _attach_context(tasks, events, bucket_min, project)
    return tasks


def _start_task(ev: dict, prompt_files: list[str]) -> dict:
    return {
        "ts_start": ev["ts"],
        "ts_end": ev["ts"],
        "bucket_id_start": None,  # filled by caller
        "source_set": {ev["source"]},
        "user_prompt": ev["text"].strip(),
        "follow_up_prompts": [],
        "files_seed": list(prompt_files),
        "meta_seed": dict(ev.get("meta") or {}),
    }


def _merge_into(active: dict, ev: dict, prompt_files: list[str]) -> None:
    active["ts_end"] = max(active["ts_end"], ev["ts"])
    active["source_set"].add(ev["source"])
    active["follow_up_prompts"].append(ev["text"].strip()[:300])
    for f in prompt_files:
        if f not in active["files_seed"]:
            active["files_seed"].append(f)


def _attach_context(tasks: list[dict], events: list[dict],
                    bucket_min: int, project: Path) -> None:
    """Walk all non-user events, attach to task whose [ts_start, ts_end+pad]
    window covers them. Pad with +bucket_min on the end to catch trailing
    asst_msg / tool_use that happened just after the last prompt of a task."""
    pad_s = bucket_min * 60
    for t in tasks:
        t["bucket_id_start"] = bucket_id(t["ts_start"], bucket_min)
        t["files_touched_all"] = list(t["files_seed"])
        t["files_touched_in_proj"] = []
        t["tool_calls"] = {}
        t["ship_hits_clean"] = []
        t["bug_hits"] = []
        t["defer_hits"] = []
        t["memory_writes"] = []
        t["plan_refs"] = []
        t["git_commits"] = []

    proj_str = str(project.resolve())
    for ev in events:
        if ev["kind"] in ("user_prompt", "convo_user"):
            continue
        ev_ts = ev["ts"]
        owner = None
        for t in tasks:
            if t["ts_start"] <= ev_ts <= (t["ts_end"] + timedelta(seconds=pad_s)):
                owner = t
                break
        if owner is None:
            continue
        owner["source_set"].add(ev["source"])
        # files
        for f in ev["files"]:
            if f not in owner["files_touched_all"]:
                owner["files_touched_all"].append(f)
            try:
                fp = str(Path(f).resolve())
                if fp.startswith(proj_str + os.sep) or fp == proj_str:
                    rel = str(Path(fp).relative_to(proj_str))
                    if rel not in owner["files_touched_in_proj"]:
                        owner["files_touched_in_proj"].append(rel)
            except (OSError, ValueError):
                pass
        # tools
        for tool in (ev.get("meta") or {}).get("tools", []) or []:
            owner["tool_calls"][tool] = owner["tool_calls"].get(tool, 0) + 1
        # ship / bug / defer denoising
        if ev["kind"] == "asst_msg":
            text = ev["text"]
            has_files = bool(ev["files"]) or bool(owner["files_touched_all"])
            ship = classify_ship(text, has_files)
            if ship:
                owner["ship_hits_clean"].append(ship)
            head = text.strip().split("\n", 1)[0][:200]
            if BUG_RE.search(head) and not SHIP_STRONG_RE.search(head):
                owner["bug_hits"].append(head)
            if DEFER_RE.search(head):
                owner["defer_hits"].append(head)
        elif ev["kind"] == "memory_write":
            owner["memory_writes"].append(ev["text"])
        elif ev["kind"] == "plan_write":
            owner["plan_refs"].append(ev["text"])
        elif ev["kind"] == "git_commit":
            sha = (ev.get("meta") or {}).get("shaShort", "")
            owner["git_commits"].append({"sha": sha, "subj": ev["text"][:120]})


# ---------- Pass 2 — soft-boundary reconciliation ----------

def pass2_merge(tasks: list[dict]) -> list[dict]:
    """Walk task list once. Merge adjacent tasks that share files or have
    a short follow-up bridge. Idempotent — does one pass."""
    if len(tasks) < 2:
        return tasks
    out: list[dict] = []
    i = 0
    while i < len(tasks):
        cur = tasks[i]
        if i + 1 >= len(tasks):
            out.append(cur)
            break
        nxt = tasks[i + 1]
        # Bridge if next is within 1 bucket of current AND shares ≥1 file
        # OR next user_prompt is short (the explicit "is_continuation" but
        # across bucket boundary).
        bridge = False
        if nxt["bucket_id_start"] - cur["bucket_id_start"] <= 1:
            cur_files = set(cur.get("files_touched_all") or [])
            nxt_files = set(nxt.get("files_touched_all") or [])
            if cur_files & nxt_files:
                bridge = True
            if len(nxt["user_prompt"]) < CONT_SHORT_LEN:
                bridge = True
        if bridge:
            # Merge nxt into cur
            cur["ts_end"] = max(cur["ts_end"], nxt["ts_end"])
            cur["source_set"] |= nxt["source_set"]
            cur["follow_up_prompts"].append(nxt["user_prompt"][:300])
            cur["follow_up_prompts"].extend(nxt["follow_up_prompts"])
            for f in nxt.get("files_touched_all") or []:
                if f not in cur["files_touched_all"]:
                    cur["files_touched_all"].append(f)
            for f in nxt.get("files_touched_in_proj") or []:
                if f not in cur["files_touched_in_proj"]:
                    cur["files_touched_in_proj"].append(f)
            for k, v in (nxt.get("tool_calls") or {}).items():
                cur["tool_calls"][k] = cur["tool_calls"].get(k, 0) + v
            for key in ("ship_hits_clean", "bug_hits", "defer_hits",
                        "memory_writes", "plan_refs", "git_commits"):
                cur[key].extend(nxt.get(key) or [])
            out.append(cur)
            i += 2
        else:
            out.append(cur)
            i += 1
    return out


# ---------- project-scope filter ----------

def task_in_project(t: dict, project: Path) -> bool:
    """Permissive scope match: keep tasks that touched a file in project
    OR had cwd inside project OR have ANY work signal (Bug 1 fix)."""
    if t.get("files_touched_in_proj"):
        return True
    cwd = (t.get("meta_seed") or {}).get("cwd") or ""
    if cwd:
        try:
            cp = Path(cwd).resolve()
            pp = project.resolve()
            if cp == pp or pp in cp.parents or cp in pp.parents:
                return True
        except OSError:
            pass
    # Keep tasks with git commits in project (already filtered to project by
    # harvest_git running git log inside project).
    if t.get("git_commits"):
        return True
    return False


# ---------- output shaping ----------

def task_to_record(t: dict, project: Path) -> dict:
    pp = project.resolve()
    src = sorted(t["source_set"])
    return {
        "ts_start": t["ts_start"].isoformat(),
        "ts_end": t["ts_end"].isoformat(),
        "duration_min": round(
            (t["ts_end"] - t["ts_start"]).total_seconds() / 60.0, 1),
        "bucket_id": t["bucket_id_start"],
        "source_set": src,
        "user_prompt": t["user_prompt"][:400],
        "follow_up_prompts": t["follow_up_prompts"][:8],
        "files_touched_all": t["files_touched_all"][:20],
        "files_touched_in_proj": t["files_touched_in_proj"][:20],
        "tool_calls": t["tool_calls"],
        "ship_hits_clean": t["ship_hits_clean"][:5],
        "bug_hits": t["bug_hits"][:3],
        "defer_hits": t["defer_hits"][:3],
        "memory_writes": t["memory_writes"][:10],
        "plan_refs": t["plan_refs"][:5],
        "git_commits": t["git_commits"][:5],
        "n_user_total": 1 + len(t["follow_up_prompts"]),  # Bug 2 fix
        "cwd": (t.get("meta_seed") or {}).get("cwd"),
        "sessionId": (t.get("meta_seed") or {}).get("sessionId"),
    }


# ---------- install-time ask + config ----------

def _config_path(project: Path) -> Path:
    return project / "board" / "discover.config.json"


def load_config(project: Path) -> dict:
    p = _config_path(project)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_config(project: Path, cfg: dict) -> None:
    p = _config_path(project)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass


def find_convo_dir(project: Path, asked: bool = False) -> Path | None:
    """Search known-safe locations. Returns first hit or None."""
    cfg = load_config(project)
    if cfg.get("convo_dir"):
        p = Path(cfg["convo_dir"]).expanduser()
        if p.is_dir():
            return p
    candidates = [
        Path.home() / "Desktop" / "conversation_history",
        Path.home() / "conversation_history",
        project / "conversation_history",
    ]
    for c in candidates:
        if c.is_dir() and any(c.glob("conversation_raw_*.md")):
            return c
    return None


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, default=Path.cwd())
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--bucket-min", type=int, default=10)
    ap.add_argument("--max-tasks", type=int, default=40)
    ap.add_argument("--all-projects", action="store_true",
                    help="don't filter tasks by project")
    ap.add_argument("--legacy", action="store_true",
                    help="fall back to discover.py")
    ap.add_argument("--ask-convo", action="store_true",
                    help="ask for conversation dir if not auto-found")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.legacy:
        legacy = Path(__file__).resolve().parent / "discover.py"
        os.execvp(sys.executable, [sys.executable, str(legacy),
                                   "--project", str(args.project),
                                   "--days", str(args.days)])
        return  # not reached

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)
             if args.days > 0 else None)
    project = args.project.resolve()

    convo_dir = find_convo_dir(project)
    if convo_dir is None and args.ask_convo and sys.stdin.isatty():
        # Polite one-time install-time ask — only fires interactively.
        print("Where do you keep your conversation history? (empty = skip)",
              file=sys.stderr)
        try:
            ans = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans:
            convo_dir = Path(ans).expanduser()
            if convo_dir.is_dir():
                cfg = load_config(project)
                cfg["convo_dir"] = str(convo_dir)
                save_config(project, cfg)

    # Harvest
    events: list[dict] = []
    events.extend(harvest_jsonl(since))
    events.extend(harvest_memory(since))
    events.extend(harvest_plans(since))
    if convo_dir:
        events.extend(harvest_convo(since, convo_dir))
    events.extend(harvest_git(project, since))

    if args.debug:
        kinds: dict[str, int] = {}
        for e in events:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        print(f"events harvested: {len(events)} {kinds}", file=sys.stderr)

    tasks = extract_tasks(events, args.bucket_min, project)
    tasks = pass2_merge(tasks)

    # Project filter (Bug 1: permissive — keep tasks with ANY signal in proj)
    if not args.all_projects:
        tasks = [t for t in tasks if task_in_project(t, project)]

    tasks.sort(key=lambda t: t["ts_start"], reverse=True)
    tasks = tasks[: args.max_tasks]
    tasks.sort(key=lambda t: t["ts_start"])  # chronological for streaming

    out = {
        "project": str(project),
        "windowDays": args.days,
        "bucketMin": args.bucket_min,
        "convoDir": str(convo_dir) if convo_dir else None,
        "taskCount": len(tasks),
        "tasks": [task_to_record(t, project) for t in tasks],
    }
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
