#!/usr/bin/env bash
# board-steward SubagentStop hook — subagent auto-card (completion phase).
#
# Fires when a subagent (Agent tool / Workflow agent) finishes. Reads the
# SubagentStop JSON from stdin and hands it to the recon helper in `stop` mode,
# which pops the oldest queued subagent card (FIFO, recorded at spawn) and flies
# it -> done, scanning the subagent's transcript for nested spawns (-> subtask)
# and explicit bug markers (-> writeup warning). Read-only subagents leave a
# skip-marker at spawn, so their stop is a silent no-op. See
# project_agent_to_agent_next.md.
#
# Silent (exit 0, no output) — unlike the main Stop hook this NEVER blocks: a
# subagent doesn't carry the board protocol, so blocking it to "card now" would
# just trap it. The carding is done here, autonomously. 6s hard timeout.

set +e
set -u

PYHELPER="$(dirname "$0")/_hook_subagent_recon.py"
if [ ! -f "${PYHELPER}" ]; then
  exit 0
fi

PAYLOAD="$(cat)"

(
  printf '%s' "${PAYLOAD}" | python3 "${PYHELPER}" stop &
  pid=$!
  ( sleep 6 ; kill -9 "${pid}" 2>/dev/null ) &
  watcher=$!
  wait "${pid}" 2>/dev/null
  kill -9 "${watcher}" 2>/dev/null
) >/dev/null 2>&1

exit 0
