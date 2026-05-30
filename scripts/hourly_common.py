#!/usr/bin/env python3
"""hourly_extractor digest primitives — extracted from hourly_extractor.py (#307 file-split).

The LLM-call config constants + the event→text digest builder. Shared by the
LLM dispatch (hourly_extractor) AND the reconciliation sweep (hourly_reconcile),
so it lives in this leaf module to keep the dependency graph acyclic.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
_LLM_MODEL = os.environ.get("HOURLY_MODEL", "haiku")


# ---------- digest builder ------------------------------------------------

def _bucket_hour(ts: datetime, bucket_min: int = 60) -> int:
    return int(ts.timestamp()) // (bucket_min * 60)


def _bucket_label(bucket: int, bucket_min: int = 60) -> str:
    dt = datetime.fromtimestamp(bucket * bucket_min * 60, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


# #299 DIGEST-COMPACT: the lossless token-cut layer lives in its own module
# (scripts/digest_compact.py) so all future token work has ONE identifiable home
# and the logic is exportable on its own. build_digest just assembles the raw
# lines; digest_compact.compact() drops the zero-signal boilerplate.
import digest_compact


def build_digest(bucket_events: list[dict], project: Path,
                 seen_heads: set | None = None) -> str:
    """Chronological digest of an hour of events for the LLM. Assembles raw
    lines, then hands them to digest_compact.compact() for the lossless cut.
    Pass a shared `seen_heads` set across buckets/chunks to dedup repeated
    non-signal heads end-to-end."""
    lines: list[str] = []
    for ev in bucket_events:
        ts = ev["ts"].strftime("%H:%M:%S")
        kind = ev["kind"]
        if kind in ("user_prompt", "convo_user"):
            txt = (ev.get("text") or "").strip().replace("\n", " ")[:400]
            lines.append(f"  [{ts}] USER: {txt}")
        elif kind in ("asst_msg", "convo_asst"):
            txt = (ev.get("text") or "").strip()
            # Just the head — full asst replies are too long
            head = txt.split("\n", 1)[0][:300]
            files = ev.get("files") or []
            if files:
                fnames = ", ".join(Path(f).name for f in files[:5])
                lines.append(f"  [{ts}] CLAUDE edited: {fnames}")
            if head:
                lines.append(f"  [{ts}] CLAUDE: {head}")
        elif kind == "git_commit":
            sha = (ev.get("meta") or {}).get("shaShort", "")
            lines.append(f"  [{ts}] COMMIT {sha}: {ev['text'][:120]}")
        elif kind == "memory_write":
            lines.append(f"  [{ts}] MEMORY: {ev['text']}")
        elif kind == "plan_write":
            lines.append(f"  [{ts}] PLAN: {ev['text']}")
    return "\n".join(digest_compact.compact(lines, seen_heads))



__all__ = ["_CLAUDE_BIN", "_LLM_MODEL", "_bucket_hour", "_bucket_label", "build_digest"]
