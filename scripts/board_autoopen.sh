#!/usr/bin/env bash
# #73 — Auto-open the board in the browser UNLESS it's already visible in Google
# Chrome. Replaces the old sseClients gate: a *stale* SSE connection (a closed/
# backgrounded tab whose socket hadn't torn down) counted as "open" even when no
# Chrome tab showed the board — so a freshly-launched Claude skipped the open and
# the user saw nothing ("opened in backend, not in Chrome"). We now ask Chrome
# directly (AppleScript) whether a tab has the board URL, and open iff it does
# not. Opening prefers Chrome (the user's browser).
#
# Falls back to the sseClients heuristic when Chrome state can't be read
# (non-macOS, no osascript, or Automation permission denied) so non-Mac/remote
# users keep working. Honours BOARD_NO_AUTO_OPEN=1 (headless/CI/cron).
#
# Usage: board_autoopen.sh <port> [project_dir]
set -u
port="${1:?need port}"
project_dir="${2:-}"
[ "${BOARD_NO_AUTO_OPEN:-0}" = "1" ] && exit 0

url="http://127.0.0.1:${port}"
match="127.0.0.1:${port}"

# Don't open a dead URL — the board's server must be live.
curl -s --max-time 0.4 "${url}/health" >/dev/null 2>&1 || exit 0

# --- Is the board already visible in Chrome? --------------------------------
# chrome_state: 0=yes (a tab has it → skip), 1=no (open it), 2=unknown (fallback)
chrome_state=2
if command -v osascript >/dev/null 2>&1; then
  if pgrep -x "Google Chrome" >/dev/null 2>&1; then
    # Query via System Events so we never LAUNCH Chrome just to inspect it.
    res="$(osascript <<AS 2>/dev/null
tell application "System Events"
  if (exists process "Google Chrome") then
    tell application "Google Chrome"
      repeat with w in windows
        repeat with t in tabs of w
          if (URL of t) contains "${match}" then return "yes"
        end repeat
      end repeat
    end tell
  end if
end tell
return "no"
AS
)"
    rc=$?
    if [ "$rc" -ne 0 ]; then chrome_state=2          # AS error / permission denied
    elif [ "$res" = "yes" ]; then chrome_state=0     # a Chrome tab has the board
    else chrome_state=1                              # Chrome up, no such tab
    fi
  else
    chrome_state=1                                   # Chrome not running → open it
  fi
fi

should_open=0
case "$chrome_state" in
  0) should_open=0 ;;
  1) should_open=1 ;;
  2) # Unknown → fall back to the old sseClients proxy.
     sse="$(curl -s --max-time 0.4 "${url}/health" | python3 -c "import sys,json
try: print(int(json.load(sys.stdin).get('sseClients',0)))
except Exception: print(0)" 2>/dev/null || echo 0)"
     [ "${sse:-0}" -eq 0 ] && should_open=1 ;;
esac

[ "$should_open" -eq 1 ] || exit 0

# Sweep stale #367 open-stamps for this project, then open (prefer Chrome).
[ -n "$project_dir" ] && rm -f "${project_dir}"/board/.opened-* 2>/dev/null
if command -v open >/dev/null 2>&1; then
  { open -a "Google Chrome" "${url}" 2>/dev/null || open "${url}" 2>/dev/null ; } &
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "${url}" >/dev/null 2>&1 &
fi
disown 2>/dev/null || true
exit 0
