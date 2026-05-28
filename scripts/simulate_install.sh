#!/usr/bin/env bash
# simulate_install.sh — replay the first-user install moment for board-steward.
#
# Spawns an isolated board server on a chosen port, pointed at a chosen
# project's session history. serve.py --bootstrap auto-discovers cards from
# ~/.claude/projects/*/sessions/*.jsonl and streams them in via SSE — the
# user opens the browser and watches the board fill itself from their real
# work history.
#
# Idempotent: tearing down any existing sim on the same port + wiping the
# sim dir before re-running is safe. Real boards on :7891/:7892 are never
# touched (this script refuses those ports).
#
# Usage:
#   scripts/simulate_install.sh                         # defaults: HFTAgents, :7894
#   scripts/simulate_install.sh --project PATH
#   scripts/simulate_install.sh --project PATH --port 7895
#   scripts/simulate_install.sh --project PATH --sim-dir ~/Desktop/my-sim
#   scripts/simulate_install.sh --no-open               # skip browser open
#   scripts/simulate_install.sh --days 14 --max 30      # bootstrap reach
#
set -euo pipefail

# ---- defaults ----------------------------------------------------------------
PROJECT="${HOME}/Desktop/QuantifyMe/HFTAgents"
PORT=7894
SIM_DIR=""                          # default derived below from date stamp
DAYS=7
MAX=20
OPEN_BROWSER=1
PROFILE="software"

# ---- arg parsing -------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)  PROJECT="$2"; shift 2 ;;
    --port)     PORT="$2"; shift 2 ;;
    --sim-dir)  SIM_DIR="$2"; shift 2 ;;
    --days)     DAYS="$2"; shift 2 ;;
    --max)      MAX="$2"; shift 2 ;;
    --profile)  PROFILE="$2"; shift 2 ;;
    --no-open)  OPEN_BROWSER=0; shift ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# //; s/^#$//'
      exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# Refuse to clobber real boards.
if [[ "$PORT" == "7891" || "$PORT" == "7892" ]]; then
  echo "✗ refusing to use port $PORT (live QM/WB board). Pick another." >&2
  exit 2
fi

# Default sim dir = date-stamped scratch under ~/Desktop.
if [[ -z "$SIM_DIR" ]]; then
  SIM_DIR="${HOME}/Desktop/board-sim-$(date +%y%m%d)"
fi

# Resolve script location → repo root → serve.py path.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SERVE_PY="${SCRIPT_DIR}/serve.py"
if [[ ! -f "$SERVE_PY" ]]; then
  echo "✗ serve.py not found at $SERVE_PY" >&2
  exit 1
fi

PROJECT_ABS="$( cd "$PROJECT" && pwd )"
if [[ ! -d "$PROJECT_ABS" ]]; then
  echo "✗ project dir not found: $PROJECT" >&2
  exit 1
fi

echo "── board-steward simulate_install ────────────────────────────────"
echo "  project      $PROJECT_ABS"
echo "  sim-dir      $SIM_DIR"
echo "  port         $PORT"
echo "  discover     last ${DAYS}d, max ${MAX} sessions → cards"
echo "──────────────────────────────────────────────────────────────────"

# ---- teardown any prior sim on this port -------------------------------------
if lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
  echo "↻ killing existing process on :$PORT"
  lsof -ti tcp:"$PORT" | xargs kill -9 2>/dev/null || true
  sleep 0.3
fi

# ---- wipe + recreate sim dir -------------------------------------------------
if [[ -d "$SIM_DIR" ]]; then
  echo "↻ wiping existing sim dir $SIM_DIR"
  rm -rf "$SIM_DIR"
fi
mkdir -p "$SIM_DIR"

# ---- spawn server ------------------------------------------------------------
LOG_FILE="${SIM_DIR}/serve.log"
echo "▶ spawning serve.py --bootstrap"
nohup python3 "$SERVE_PY" \
  --bootstrap \
  --no-discover \
  --project "$SIM_DIR" \
  --port "$PORT" \
  --profile "$PROFILE" \
  --title "WorkBoard — $(basename "$PROJECT_ABS") (sim)" \
  > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "  pid=$SERVER_PID  log=$LOG_FILE"

# ---- wait for health ---------------------------------------------------------
for i in {1..30}; do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done
if ! curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "✗ server didn't come up on :$PORT — check $LOG_FILE" >&2
  exit 1
fi

# The bootstrap discovery thread runs in the background and streams cards via
# SSE; cards may still be arriving when the browser opens (that's the point —
# user sees them pop in live). Discovery streams real session history from the
# REAL project at $PROJECT_ABS, but writes cards into the SIM board.
#
# Note: serve.py --project is what controls where discovery walks for cwd
# matches. It also controls where the board lives. Same arg, two roles. So
# for a "fresh install on dir X" sim we point --project at the SIM dir (above)
# — discover.py walks ~/.claude/projects/*/sessions/*.jsonl and includes
# sessions whose cwd is at/under the sim dir, which is empty, so no cards
# stream. For "first-user feel on REAL history of project X" we'd swap
# --project to point at X — but then the sim's board.json would live INSIDE
# X, polluting it. The clean compromise: this script kicks off discovery
# manually pointed at the real project, via a one-shot subprocess invocation
# of card.py (mirroring what _stream_discovered_cards does in serve.py).

echo "▶ discovering real cards from $PROJECT_ABS history"
export SIM_BOARD_DIR="${SIM_DIR}/board"
python3 - "$PROJECT_ABS" "$PORT" "$DAYS" "$MAX" "${SCRIPT_DIR}" <<'PYEOF'
import sys, subprocess, json, time, urllib.request, urllib.parse
project, port, days, mx, sdir = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
# Run discover.py against the REAL project — emits sessions as JSON
proc = subprocess.run(
    ["python3", f"{sdir}/discover.py", "--project", project,
     "--days", days, "--max-sessions", mx],
    capture_output=True, text=True
)
if proc.returncode != 0:
    print(f"discover.py failed: {proc.stderr[:400]}", file=sys.stderr)
    sys.exit(0)  # don't break the script
try:
    sessions = json.loads(proc.stdout).get("sessions", [])
except json.JSONDecodeError:
    print(f"discover.py returned non-JSON: {proc.stdout[:200]}", file=sys.stderr)
    sys.exit(0)
# Sort oldest first so the live UI fills chronologically.
sessions.sort(key=lambda s: s.get("startedAt", ""))
print(f"  → {len(sessions)} sessions to stream into sim board")
import os
env = os.environ.copy()
env["BOARD_SERVER"] = f"http://127.0.0.1:{port}"
# Use serve.py's own session→card mapper for column heuristics — import it.
sys.path.insert(0, sdir)
from serve import _session_to_card_args
for sess in sessions:
    args = _session_to_card_args(sess)
    if not args:
        continue
    sim_board_json = os.path.join(os.environ.get("SIM_BOARD_DIR", ""), "board.json")
    try:
        subprocess.run(
            ["python3", f"{sdir}/card.py", "--board", sim_board_json, "add"] + args,
            env=env, capture_output=True, text=True, timeout=8
        )
    except Exception as e:
        print(f"  ! card add failed: {e}", file=sys.stderr)
    time.sleep(0.25)  # 250ms pacing — same as serve.py default
PYEOF

# ---- final report ------------------------------------------------------------
HEALTH=$(curl -s "http://127.0.0.1:${PORT}/health")
echo ""
echo "✓ sim board live"
echo "  URL    http://127.0.0.1:${PORT}/"
echo "  health $HEALTH"
echo "  log    $LOG_FILE"
echo "  stop   kill $SERVER_PID   (or: lsof -ti tcp:$PORT | xargs kill)"
echo ""

if [[ "$OPEN_BROWSER" == "1" ]]; then
  if command -v open >/dev/null 2>&1; then
    open "http://127.0.0.1:${PORT}/"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:${PORT}/"
  fi
fi
