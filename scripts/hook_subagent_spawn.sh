#!/usr/bin/env bash
# board-steward PreToolUse(Agent) hook — subagent auto-card (spawn phase).
#
# Fires when a subagent (Agent tool / Workflow agent) is about to launch. Reads
# the PreToolUse JSON from stdin and hands it to the recon helper in `spawn`
# mode, which (unless the subagent_type is read-only) adds a card and flies it
# task -> inprogress, then records it on a FIFO queue for the matching
# SubagentStop to close. The "every task labelled regardless of source"
# guarantee for subagents — see project_agent_to_agent_next.md.
#
# Must NOT block the spawn. Exits 0 always. 6s hard timeout (carding does two
# card.py calls with brief animation pauses; a subagent launch is heavy enough
# that a sub-second card delay is negligible).

set +e
set -u

PYHELPER="$(dirname "$0")/_hook_subagent_recon.py"
if [ ! -f "${PYHELPER}" ]; then
  exit 0
fi

PAYLOAD="$(cat)"

(
  printf '%s' "${PAYLOAD}" | python3 "${PYHELPER}" spawn &
  pid=$!
  ( sleep 6 ; kill -9 "${pid}" 2>/dev/null ) &
  watcher=$!
  wait "${pid}" 2>/dev/null
  kill -9 "${watcher}" 2>/dev/null
) >/dev/null 2>&1

exit 0
