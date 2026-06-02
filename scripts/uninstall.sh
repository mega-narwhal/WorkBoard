#!/usr/bin/env bash
#
# uninstall.sh — remove board-steward's runtime side-effects.
#
# Board-steward installs as a Claude Code plugin, but at runtime it also creates
# things the plugin system does NOT track and `/plugin uninstall` will NOT remove:
#   - an autostart agent (launchd / systemd / Task Scheduler) running serve.py
#   - the live board HTTP server (on its port)
#   - legacy settings-based hooks (pre-plugin installs only)
#   - the ~/.board-steward/ port registry  (only with --purge)
#
# This script cleans those up. It does NOT delete the plugin code itself or your
# board.json — run `/plugin uninstall board-steward@workboard` in Claude Code for
# the plugin files, and your board/ dir is project data you keep or delete yourself.
#
# Usage:
#   ./uninstall.sh                 # stop autostart + server, remove legacy hooks
#   ./uninstall.sh --port 7891     # be explicit about which server port to free
#   ./uninstall.sh --purge         # also remove ~/.board-steward/ port registry
#   ./uninstall.sh --dry-run       # show what would happen, change nothing
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=""
PURGE=0
DRY=0
DRY_FLAG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --port)    PORT="$2"; shift 2 ;;
    --purge)   PURGE=1; shift ;;
    --dry-run) DRY=1; DRY_FLAG="--dry-run"; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

run() { if [ "$DRY" = 1 ]; then echo "DRY-RUN: $*"; else eval "$*"; fi; }

echo "board-steward uninstall — removing runtime side-effects"
echo "  (plugin code + board.json are left alone; see header)"
echo ""

# 1. autostart agent (launchd/systemd/taskscheduler) — also stops the KeepAlive server
echo "1) removing autostart agent…"
python3 "$SCRIPT_DIR/install_autostart.py" --uninstall $DRY_FLAG || echo "   (autostart already absent)"

# 2. belt-and-suspenders: free the port if a stray server still holds it
if [ -n "$PORT" ]; then
  STRAY="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
  if [ -n "$STRAY" ]; then
    echo "2) freeing port $PORT (stray pid $STRAY)…"
    run "kill $STRAY 2>/dev/null || true"
  else
    echo "2) port $PORT already free"
  fi
else
  echo "2) no --port given; skipping stray-port check"
fi

# 3. legacy settings-based hooks (no-op on a clean plugin install)
echo "3) removing any legacy settings-based hooks…"
python3 "$SCRIPT_DIR/install_hooks.py" --uninstall $DRY_FLAG || echo "   (no legacy hooks)"

# 4. optional: purge the port registry / state dir
if [ "$PURGE" = 1 ]; then
  echo "4) purging ~/.board-steward/ …"
  run "rm -rf \"$HOME/.board-steward\""
else
  echo "4) keeping ~/.board-steward/ (pass --purge to remove)"
fi

echo ""
echo "✓ runtime side-effects removed."
echo "  To remove the plugin itself, in Claude Code run:"
echo "      /plugin uninstall board-steward@workboard"
echo "      /plugin marketplace remove workboard   # optional"
echo "  Your board/ dir (board.json + history) was left untouched."
