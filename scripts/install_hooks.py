#!/usr/bin/env python3
"""
install_hooks.py — idempotently wire board-steward hooks into Claude Code settings.

Why: SKILL.md v1-v4 documented hooks as "opt-in copy-pasteable snippets." Nobody
installed them. The board then silently drifts during long active-coding sessions
(see card #84). This script makes hook installation a one-line step every new
user can run after `pip install` / `git clone`.

Usage:
    install_hooks.py              # install (idempotent)
    install_hooks.py --dry-run    # show diff, don't write
    install_hooks.py --uninstall  # remove our hook entry
    install_hooks.py --status     # report current install state

Resolves its own location via __file__, so the hook command path in
settings.json points to wherever the skill happens to live on this machine.
No hardcoded /Users/* anywhere.

Safe to run repeatedly — detects existing entries by command-path match.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


HOOK_SCRIPT_NAME = "hook_user_prompt.sh"
HOOK_EVENT = "UserPromptSubmit"


def claude_settings_path() -> Path:
    """Resolve Claude Code's user settings.json — honors $CLAUDE_CONFIG_DIR."""
    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".claude"
    return base / "settings.json"


def hook_command() -> str:
    """Absolute path to our hook script, computed at install-time."""
    return str((Path(__file__).resolve().parent / HOOK_SCRIPT_NAME).resolve())


def load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"refusing to touch malformed settings.json ({path}): {e}")


def find_existing(settings: dict, cmd: str) -> tuple[int, int] | None:
    """Return (group_idx, hook_idx) of our entry, or None."""
    hooks = settings.get("hooks", {}).get(HOOK_EVENT, [])
    for gi, group in enumerate(hooks):
        for hi, hook in enumerate(group.get("hooks", [])):
            if hook.get("type") == "command" and hook.get("command") == cmd:
                return gi, hi
    return None


def install(settings: dict, cmd: str) -> tuple[dict, str]:
    """Return (new_settings, action). Idempotent."""
    existing = find_existing(settings, cmd)
    if existing is not None:
        return settings, "already-installed"

    settings.setdefault("hooks", {}).setdefault(HOOK_EVENT, []).append({
        "matcher": "",
        "hooks": [{"type": "command", "command": cmd}],
    })
    return settings, "installed"


def uninstall(settings: dict, cmd: str) -> tuple[dict, str]:
    hooks = settings.get("hooks", {}).get(HOOK_EVENT, [])
    removed = False
    new_groups = []
    for group in hooks:
        new_hooks = [h for h in group.get("hooks", [])
                     if not (h.get("type") == "command" and h.get("command") == cmd)]
        if len(new_hooks) != len(group.get("hooks", [])):
            removed = True
        if new_hooks:
            new_groups.append({**group, "hooks": new_hooks})
    if removed:
        if new_groups:
            settings["hooks"][HOOK_EVENT] = new_groups
        else:
            settings["hooks"].pop(HOOK_EVENT, None)
            if not settings["hooks"]:
                settings.pop("hooks", None)
        return settings, "uninstalled"
    return settings, "not-installed"


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bk = path.with_suffix(path.suffix + f".bak-{stamp}")
    shutil.copy2(path, bk)
    return bk


def cmd_status(args) -> int:
    path = claude_settings_path()
    cmd = hook_command()
    print(f"settings.json: {path} {'(exists)' if path.exists() else '(missing)'}")
    print(f"hook script:   {cmd}")
    print(f"hook script exists+executable: {Path(cmd).exists() and os.access(cmd, os.X_OK)}")
    settings = load_settings(path)
    if find_existing(settings, cmd):
        print("STATUS: ✓ INSTALLED")
        return 0
    print("STATUS: ✗ NOT INSTALLED — run `install_hooks.py` to wire it up.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show what would change; don't write")
    ap.add_argument("--uninstall", action="store_true", help="remove the hook entry")
    ap.add_argument("--status", action="store_true", help="report current state")
    ap.add_argument("--no-backup", action="store_true", help="skip the .bak-<ts> snapshot")
    args = ap.parse_args()

    if args.status:
        return cmd_status(args)

    path = claude_settings_path()
    cmd = hook_command()

    if not Path(cmd).exists():
        sys.exit(f"hook script missing at {cmd} — re-install the skill, then retry")

    settings = load_settings(path)
    if args.uninstall:
        new_settings, action = uninstall(settings, cmd)
    else:
        new_settings, action = install(settings, cmd)

    if args.dry_run:
        print(f"DRY-RUN: action={action}")
        print(f"  settings.json: {path}")
        print(f"  hook command:  {cmd}")
        print("--- would-be contents ---")
        print(json.dumps(new_settings, indent=2))
        return 0

    if action in ("already-installed", "not-installed"):
        print(f"no-op ({action}) — {path}")
        return 0

    if not args.no_backup and path.exists():
        bk = backup(path)
        if bk:
            print(f"backup: {bk}")
    atomic_write(path, new_settings)
    print(f"{action} hook → {path}")
    print(f"  command: {cmd}")
    print("(restart any open Claude Code session to pick up the new hook)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
