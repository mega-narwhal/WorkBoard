#!/usr/bin/env bash
# board-steward Stop hook for #279 STOP-RECON-HOOK.
#
# Fires when the agent finishes responding (session sign-off). Reads the Stop
# JSON from stdin, hands it to the recon helper which checks whether this turn's
# work got carded + whether anything is still In-Progress. It always writes
# board/recon_pending.json on a gap (deferred backstop), AND — on un-carded work —
# emits {"decision":"block","reason":...} on stdout to refuse the stop so Claude
# cards it NOW (the LIVE 100% guarantee). Single-shot via the helper's
# stop_hook_active loop guard. The live "never-miss on sign-off" backstop.
#
# Hard timeout 5s. Silent (exit 0, no output) unless the helper emits a block.

set +e
set -u

PYHELPER="$(dirname "$0")/_hook_stop_recon.py"
if [ ! -f "${PYHELPER}" ]; then
  exit 0
fi

# Capture the Stop payload from stdin BEFORE backgrounding — a backgrounded
# process's stdin is detached from the pipe, and the helper needs the payload's
# transcript_path/cwd. Feed it back in via a pipe.
PAYLOAD="$(cat)"

# 5s hard timeout (a large session transcript takes a moment to scan); macOS has
# no `timeout`, so background + kill-on-overrun. Session-end, so no user latency.
# CAPTURE the helper's stdout (NOT >/dev/null): on an un-carded-work gap it emits
# {"decision":"block","reason":...}, which we must pass through to our own stdout
# for Claude Code to honor. stderr is still discarded.
OUT="$(
  printf '%s' "${PAYLOAD}" | python3 "${PYHELPER}" 2>/dev/null &
  pid=$!
  ( sleep 5 ; kill -9 "${pid}" 2>/dev/null ) &
  watcher=$!
  wait "${pid}" 2>/dev/null
  kill -9 "${watcher}" 2>/dev/null
)"

# Emit the decision JSON (if any) so a block reaches Claude Code; empty = no block.
[ -n "${OUT}" ] && printf '%s\n' "${OUT}"
exit 0
