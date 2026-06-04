#!/usr/bin/env bash
# clean_slate.sh — full board-steward teardown for a fresh-user / first-run test.
#
# Backs up first, then removes EVERYTHING that could make a later reinstall reuse
# stale state or skip the first-run popup:
#   1. backup → ~/board-steward-cleanslate-backup-<ts>/ (board.json(s), ~/.board-steward, plists)
#   2. stop + remove autostart (launchd com.boardsteward.*)
#   3. kill every server on the board port range (7891-7999) + stray serve.py
#   4. purge ~/.board-steward  (port registry + .onboarded marker)
#   5. delete board.json(s) + runtime sidecars so the next run bootstraps fresh
#   6. (default) uninstall the plugin so reinstall is truly clean
#   7. (default) clear the plugin CACHE so the reinstall pulls FRESH repo code
#      (uninstall alone leaves ~/.claude/plugins/cache; installs key by version,
#       so a same-version reinstall would replay stale cached files)
#
# Idempotent. Restore from the printed backup dir. Flags:
#   --dry-run     show what would happen, change nothing
#   --no-plugin   keep the installed plugin (only wipe runtime state)
#   --repo=PATH   board repo (default: ~/Desktop/WorkBoard)
set -u
PORT_LO=7891; PORT_HI=7999
DRY=0; DO_PLUGIN=1; REPO="${BOARD_REPO:-$HOME/Desktop/WorkBoard}"
for a in "$@"; do case "$a" in
  --dry-run)   DRY=1 ;;
  --no-plugin) DO_PLUGIN=0 ;;
  --repo=*)    REPO="${a#--repo=}" ;;
  *) echo "unknown arg: $a" >&2 ;;
esac; done
run(){ echo "  \$ $*"; [ "$DRY" = 1 ] || eval "$@"; }
label=""; [ "$DRY" = 1 ] && label=" (DRY RUN)"

TS=$(date +%Y%m%d-%H%M%S)
BK="$HOME/board-steward-cleanslate-backup-$TS"
echo "== board-steward clean-slate${label} =="
echo "backup → $BK"
[ "$DRY" = 1 ] || mkdir -p "$BK"

# Collect board dirs: registry keys + the default repo board.
ASSIGN="$HOME/.board-steward/port-assignments.json"
BOARD_DIRS="$REPO/board"
if [ -f "$ASSIGN" ]; then
  more=$(python3 -c "import json;print('\n'.join(json.load(open('$ASSIGN')).keys()))" 2>/dev/null)
  BOARD_DIRS="$BOARD_DIRS
$more"
fi
BOARD_DIRS=$(printf '%s\n' "$BOARD_DIRS" | sort -u | sed '/^$/d')

echo "--- 1. backup ---"
[ -d "$HOME/.board-steward" ] && run cp -R "$HOME/.board-steward" "$BK/dot-board-steward"
printf '%s\n' "$BOARD_DIRS" | while read -r bd; do
  [ -f "$bd/board.json" ] && run cp "$bd/board.json" "$BK/boardjson_$(echo "$bd" | tr '/ ' '__').json"
done
for p in "$HOME"/Library/LaunchAgents/*boardsteward*.plist; do [ -f "$p" ] && run cp "$p" "$BK/"; done

echo "--- 2. remove autostart (launchd) ---"
for p in "$HOME"/Library/LaunchAgents/*boardsteward*.plist; do
  [ -f "$p" ] || continue
  label=$(basename "$p" .plist)
  run "launchctl bootout gui/$(id -u)/$label 2>/dev/null || launchctl unload '$p' 2>/dev/null || true"
  run rm -f "$p"
done

echo "--- 3. kill servers on ports ${PORT_LO}-${PORT_HI} + stray serve.py ---"
pids=$(lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk -v lo=$PORT_LO -v hi=$PORT_HI \
  'NR>1{n=split($9,a,":"); p=a[n]+0; if(p>=lo && p<=hi) print $2}' | sort -u)
[ -n "$pids" ] && run "kill -9 $(echo $pids) 2>/dev/null || true" || echo "  (no listeners in range)"
run "pkill -9 -f 'serve.py --project' 2>/dev/null || true"

echo "--- 4. purge ~/.board-steward (registry + .onboarded) ---"
run rm -rf "$HOME/.board-steward"

echo "--- 5. delete board.json(s) + runtime sidecars ---"
printf '%s\n' "$BOARD_DIRS" | while read -r bd; do
  [ -d "$bd" ] || continue
  run rm -f "$bd/board.json" "$bd/index.json" "$bd/.spawn.lock" \
           "$bd/recon_pending.json" "$bd/extraction_pending.json" \
           "$bd/extraction_snapshot.json" "$bd/.subagent_queue.jsonl"
  run "rm -f '$bd'/.opened-* 2>/dev/null || true"
done

if [ "$DO_PLUGIN" = 1 ]; then
  if command -v claude >/dev/null 2>&1; then
    echo "--- 6. uninstall plugin ---"
    run "claude plugin uninstall board-steward@workboard 2>&1 | tail -2 || true"
  fi
  # 7. Clear the plugin cache so a REINSTALL pulls fresh files from the repo.
  # `claude plugin uninstall` does NOT clear ~/.claude/plugins/cache, and installs
  # key by VERSION — so reinstalling the SAME version replays STALE cached code
  # (the 260604 picker bug: reinstall kept serving an old hook). Nuking the cache
  # forces a fresh copy on next install regardless of version — no manual bump
  # needed. (--no-plugin keeps BOTH the plugin and its cache.)
  echo "--- 7. clear plugin cache (forces fresh reinstall) ---"
  found=0
  for cd in "$HOME"/.claude/plugins/cache/*/board-steward; do
    [ -e "$cd" ] || continue
    found=1
    run rm -rf "$cd"
  done
  [ "$found" = 0 ] && echo "  (no cached plugin copies found)"
fi

echo
[ "$DRY" = 1 ] && label=" (DRY RUN — nothing changed)" || label=""
echo "== clean-slate done${label} =="
echo "backup: $BK"
[ "$DRY" = 1 ] && exit 0
echo "verify:"
echo "  curl -s --max-time 0.4 http://127.0.0.1:7891/health   # expect: empty (no server)"
echo "  ls ~/.board-steward 2>&1                               # expect: No such file"
echo "Plugin cache cleared → a plain reinstall now pulls fresh repo code (no version bump needed):"
echo "  claude plugin install board-steward@workboard --scope user"
echo "Then start claude in \$HOME → first-run picker fires fresh."
