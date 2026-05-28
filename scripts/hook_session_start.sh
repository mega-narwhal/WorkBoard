#!/usr/bin/env bash
# board-steward SessionStart hook.
#
# Fires ONCE per Claude Code session, regardless of CWD or first-prompt phase.
# Injects a tight digest (~80 tokens) into context so Claude knows the board
# exists, its current shape, and the update protocol — without loading the
# full board.json on every prompt.
#
# Output goes straight into Claude's context. Exit 0 always (non-blocking).
# Cost: <100ms (one curl + one python parse of board.json).

set +e
set -u

# Walk up from CWD looking for board/board.json (max 8 levels).
dir="${PWD}"
board_path=""
for _ in 1 2 3 4 5 6 7 8; do
  if [ -f "${dir}/board/board.json" ]; then
    board_path="${dir}/board/board.json"
    break
  fi
  parent="$(dirname "${dir}")"
  [ "${parent}" = "${dir}" ] && break
  dir="${parent}"
done

# Stay silent for non-board projects.
[ -z "${board_path}" ] && exit 0

project_dir="$(dirname "$(dirname "${board_path}")")"
serve_py="$(dirname "$0")/serve.py"

# Probe for a live server.
server_health=""
for port in 7891 7892 7893 7894 7895; do
  h="$(curl -s --max-time 0.3 "http://127.0.0.1:${port}/health" 2>/dev/null)"
  if [ -n "${h}" ]; then
    server_health="${h}"
    server_port="${port}"
    break
  fi
done

# Auto-spawn if no server (covers users without launchd installed).
if [ -z "${server_health}" ] && [ -f "${serve_py}" ]; then
  lock="${project_dir}/board/.spawn.lock"
  now_ts="$(date +%s)"
  last_ts="$(stat -f %m "${lock}" 2>/dev/null || stat -c %Y "${lock}" 2>/dev/null || echo 0)"
  age=$((now_ts - last_ts))
  if [ "${age}" -gt 10 ]; then
    : > "${lock}"
    nohup python3 "${serve_py}" --project "${project_dir}" --port 7891 \
      >/tmp/board-spawn.log 2>&1 </dev/null &
    disown 2>/dev/null || true
    sleep 0.8
    server_health="$(curl -s --max-time 0.3 http://127.0.0.1:7891/health 2>/dev/null)"
    server_port="7891"
  fi
fi

# Build digest: counts by column + last shipped card (with relative time).
digest="$(python3 - "${board_path}" <<'PY' 2>/dev/null
import json, sys
from datetime import datetime, timezone

with open(sys.argv[1]) as f:
    b = json.load(f)

cards = b.get("cards", [])
cols = {c["id"]: c.get("name", c["id"]) for c in b.get("columns", [])}

counts = {}
for c in cards:
    counts[c.get("column","?")] = counts.get(c.get("column","?"), 0) + 1

done = [c for c in cards if c.get("column") == "done" and c.get("doneAt")]
done.sort(key=lambda c: c.get("doneAt",""), reverse=True)

last = "(none)"
if done:
    top = done[0]
    ds = top.get("doneAt","")
    try:
        when = datetime.fromisoformat(ds.replace("Z","+00:00"))
        delta = datetime.now(timezone.utc) - when
        hrs = int(delta.total_seconds() // 3600)
        if hrs < 1:   ago = "<1h ago"
        elif hrs < 24: ago = f"{hrs}h ago"
        else:          ago = f"{hrs//24}d ago"
    except Exception:
        ago = ds[:10]
    last = f"#{top.get('num','?')} {top.get('code','')} ({ago})"

order = ["super-urgent", "mandatory", "ideas", "backlog", "inprogress", "blocked", "done"]
seen = set()
parts = []
for k in order:
    if counts.get(k, 0):
        parts.append(f"{cols.get(k,k)}: {counts[k]}")
        seen.add(k)
# Any custom columns not in order
for k, n in counts.items():
    if k not in seen and n:
        parts.append(f"{cols.get(k,k)}: {n}")

print(" · ".join(parts))
print(f"Last shipped: {last}")
PY
)"

# Extract live rev/cards from server health (UX sugar).
live_line=""
if [ -n "${server_health}" ]; then
  parsed="$(echo "${server_health}" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f\"{d.get('rev','?')}|{d.get('cards','?')}\")
except Exception:
    pass" 2>/dev/null)"
  if [ -n "${parsed}" ]; then
    rev="${parsed%%|*}"
    n="${parsed##*|}"
    live_line="Live at http://127.0.0.1:${server_port} (rev ${rev} · ${n} cards)"
  fi
fi

# Helper path Claude will see and can call.
card_py="$(dirname "$0")/card.py"

cat <<MSG
<board-steward-session-start>
Board: ${board_path}
${live_line:-(server down — start: python3 $(dirname "$0")/serve.py --project ${project_dir})}
${digest}

Protocol: every ship/fix/defer → \`${card_py} add\` or \`${card_py} move\` immediately (no batching). Status queries → \`card.py list\` or digest above, not memory. Detail → \`card.py show <num>\`. Never auto-Read board.json.
</board-steward-session-start>
MSG

exit 0
