#!/usr/bin/env bash
# board-steward PreToolUse 'card-before-edit' WARN hook (#75, yesterday opt 3).
#
# Fires on every Edit / Write / MultiEdit / NotebookEdit (same matcher as the
# flash hook — they run as two independent PreToolUse groups). Hands the
# PreToolUse JSON to the helper, which — when the edited file is in a board
# project with NO In-Progress card — emits a NON-BLOCKING
# hookSpecificOutput.additionalContext reminder to declare the unit first
# (law #1). It NEVER blocks the edit. Conservative + debounced so it can't spam.
#
# Hard timeout 1s. Silent unless the helper emits the additionalContext JSON.

set +e
set -u

PYHELPER="$(dirname "$0")/_hook_card_before_edit.py"
if [ ! -f "${PYHELPER}" ]; then
  exit 0
fi

# Capture stdin (PreToolUse payload) BEFORE backgrounding — a backgrounded
# process's stdin detaches from the pipe, and the helper needs file_path/cwd.
PAYLOAD="$(cat)"

# 1s hard timeout so a wedged interpreter can never delay the actual Edit/Write.
# macOS ships no `timeout`, so background + kill-on-overrun. CAPTURE stdout (the
# additionalContext JSON, if any) and pass it through to our own stdout.
OUT="$(
  printf '%s' "${PAYLOAD}" | python3 "${PYHELPER}" 2>/dev/null &
  pid=$!
  ( sleep 1 ; kill -9 "${pid}" 2>/dev/null ) &
  watcher=$!
  wait "${pid}" 2>/dev/null
  kill -9 "${watcher}" 2>/dev/null
)"

[ -n "${OUT}" ] && printf '%s\n' "${OUT}"
exit 0
