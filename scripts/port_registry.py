"""Shared port registry for board-steward.

A tiny JSON file at ~/.config/board-steward/port-registry.json maps each
running board's absolute path → {port, pid, started_at}. serve.py writes its
entry on boot; card.py + hooks consult it for O(1) port lookup instead of
probing 7891-7900 every CLI call.

The registry is advisory, not authoritative — readers MUST verify the entry
is alive (the /health-ping check is the consumer's job) before trusting it.
This keeps the file self-healing across crashes / SIGKILL / laptop sleep
without needing a daemon to scrub it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


REGISTRY_ENV = "BOARD_REGISTRY"
ASSIGN_ENV = "BOARD_ASSIGNMENTS"
ACTIVE_ENV = "BOARD_ACTIVE"

# Port window for auto-designation. 7891 onwards, lowest free first — 7891 is
# assumed least-used, and each project then claims the next gap.
PORT_LO = 7891
PORT_HI = 7999

# Public for tests / inspectors. Lives directly in $HOME (not ~/.config,
# which on macOS is often root-owned and unwritable for normal users).
DEFAULT_PATH = Path.home() / ".board-steward" / "port-registry.json"
# Sticky board→port DESIGNATION, separate from the liveness registry above.
# This survives the server dying (a project keeps its port across restarts);
# the registry tracks who's live right now, this tracks who OWNS which port.
ASSIGN_PATH = Path.home() / ".board-steward" / "port-assignments.json"
# The single board the human last INTERACTED with (a card mutation, a serve, a
# bootstrap). Used by the SessionStart hook to disambiguate when Claude opens at
# $HOME with no cwd board and several boards exist: reopen the one in active
# use, not whichever board.json happens to have the newest file mtime (#mb —
# mtime picked the wrong board when two boards were edited the same session).
ACTIVE_PATH = Path.home() / ".board-steward" / "last-active"


def registry_path() -> Path:
    env = os.environ.get(REGISTRY_ENV)
    if env:
        return Path(env).expanduser()
    return DEFAULT_PATH


def assignments_path() -> Path:
    env = os.environ.get(ASSIGN_ENV)
    if env:
        return Path(env).expanduser()
    return ASSIGN_PATH


def active_path() -> Path:
    env = os.environ.get(ACTIVE_ENV)
    if env:
        return Path(env).expanduser()
    return ACTIVE_PATH


def _atomic_write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, p)


def read() -> dict:
    """Return the full registry dict, or {} if missing/corrupt."""
    p = registry_path()
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _pid_alive(pid: int) -> bool:
    """True if a process with `pid` exists. Signal 0 probes without killing."""
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        # EPERM means it exists but we can't signal it — still alive.
        return True
    return True


def prune(d: dict | None = None) -> dict:
    """Drop entries whose server PID is dead OR whose board dir no longer
    exists on disk. Returns the cleaned dict. This is the real self-heal the
    module's docstring promised: transient paths (e.g. /tmp demo runs) never
    reboot to stomp their own row, so without an active prune they accrete
    forever (#374 — registry hit 53 entries, 52 dead). Cheap: one os.kill(,0)
    + one stat per row."""
    if d is None:
        d = read()
    cleaned = {
        k: v for k, v in d.items()
        if isinstance(v, dict)
        and _pid_alive(v.get("pid", -1))
        and Path(k).exists()
    }
    return cleaned


def write(board_dir: str | os.PathLike, port: int, pid: int) -> None:
    """Register THIS process as serving `board_dir` on `port`. Idempotent.

    Prunes dead/stale rows first (self-heal), then stomps any prior entry for
    the same board path (the prior server is presumed dead)."""
    key = str(Path(board_dir).resolve())
    d = prune(read())
    d[key] = {
        "port": int(port),
        "pid": int(pid),
        "started_at": _now_iso(),
    }
    _atomic_write_json(registry_path(), d)


def remove(board_dir: str | os.PathLike) -> None:
    """Drop the entry for `board_dir`. Safe if missing."""
    key = str(Path(board_dir).resolve())
    d = read()
    if key in d:
        del d[key]
        _atomic_write_json(registry_path(), d)


def lookup(board_dir: str | os.PathLike) -> int | None:
    """Return the cached port for `board_dir`, or None if unregistered.

    Caller MUST verify the server is alive via /health before trusting it —
    this is just a hint, not a guarantee. Stale entries self-heal when the
    next serve.py for the same board path overrides."""
    key = str(Path(board_dir).resolve())
    return (read().get(key) or {}).get("port")


def assignments() -> dict:
    """Return the sticky board→port designation map, or {} if missing/corrupt."""
    p = assignments_path()
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def assign(board_dir: str | os.PathLike, preferred: int | None = None,
           lo: int = PORT_LO, hi: int = PORT_HI) -> int:
    """Return the DESIGNATED port for `board_dir`, allocating one if needed.

    The designation is sticky and persisted: a project keeps the same port
    forever (across server restarts), so every consumer resolves it the same
    way and two projects can never collide (#374 — WorkBoard + QuantifyMe both
    defaulted to 7891). Allocation rule: reuse the existing designation if the
    board already has one; else take `preferred` if it's in-window and unclaimed;
    else the lowest free port from `lo` upward. GCs designations whose board dir
    no longer exists so the window doesn't fill with dead projects."""
    key = str(Path(board_dir).resolve())
    a = {k: v for k, v in assignments().items() if Path(k).exists()}
    if key in a:
        port = int(a[key])
    else:
        taken = {int(v) for v in a.values()}
        if preferred is not None and lo <= preferred <= hi and preferred not in taken:
            port = int(preferred)
        else:
            port = next((p for p in range(lo, hi + 1) if p not in taken), lo)
        a[key] = port
    _atomic_write_json(assignments_path(), a)
    return port


def set_port(board_dir: str | os.PathLike, port: int) -> None:
    """Force `board_dir`'s designation to `port`, overwriting any prior one.
    Used after a bind to record the port that actually came up (e.g. when the
    preferred designation was held by a stray process and we walked forward)."""
    key = str(Path(board_dir).resolve())
    a = {k: v for k, v in assignments().items() if Path(k).exists()}
    a[key] = int(port)
    _atomic_write_json(assignments_path(), a)


def set_active(board_dir: str | os.PathLike) -> None:
    """Record `board_dir` as the board the human last interacted with.

    Best-effort and never raises — a failed write here must never break the
    card mutation / serve / bootstrap that triggered it. The file holds one
    line: the resolved absolute board dir."""
    try:
        key = str(Path(board_dir).resolve())
        p = active_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(key + "\n")
        os.replace(tmp, p)
    except OSError:
        pass


def get_active() -> str | None:
    """Return the last-active board dir, or None if unset / gone from disk.

    Self-heals: if the recorded board has since been deleted, returns None so
    the caller falls back (e.g. to mtime) rather than pointing at a dead dir."""
    try:
        p = active_path()
        if not p.exists():
            return None
        val = p.read_text().strip()
    except OSError:
        return None
    if not val or not Path(val).exists():
        return None
    return val


def _now_iso() -> str:
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
