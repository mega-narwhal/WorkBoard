#!/usr/bin/env bash
# board-steward PreToolUse hook for #102 BOARD-AUTO-LINK.
#
# Fires on every Edit / Write / MultiEdit / NotebookEdit. Reads the PreToolUse
# JSON from stdin, finds cards that 'own' the edited file via linkedFiles,
# and pings /flash on the live board server so its border pulses.
#
# Must be FAST and SILENT. Exits 0 always (never blocks Claude's tool call).
# Total budget < 800ms, hard timeout 1s via python.

set +e
set -u

# Pass stdin (JSON payload) straight into the helper; PWD as a fallback
# project anchor in case the payload's CWD field is missing.
PYHELPER="$(dirname "$0")/_hook_flash_linked.py"
if [ ! -f "${PYHELPER}" ]; then
  exit 0
fi

# 1-second hard timeout so a wedged Python interpreter can never delay
# Claude's actual Edit/Write call. macOS doesn't ship `timeout` by default,
# so we run via a backgrounded subshell + kill if it overruns.
(
  python3 "${PYHELPER}" "${PWD}" &
  pid=$!
  ( sleep 1 ; kill -9 "${pid}" 2>/dev/null ) &
  watcher=$!
  wait "${pid}" 2>/dev/null
  kill -9 "${watcher}" 2>/dev/null
) >/dev/null 2>&1

exit 0
