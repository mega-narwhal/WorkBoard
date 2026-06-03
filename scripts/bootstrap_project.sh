#!/usr/bin/env bash
# bootstrap_project.sh <project_root>
#
# Stand up ONE WorkBoard for the given project and open it. This is the single
# entrypoint the SessionStart picker hands to Claude after the user chooses a
# project (see hook_session_start.sh home-dir branch). Doing it in one script —
# rather than a multi-step command Claude assembles — keeps the first-run flow
# reproducible and identical to the in-project auto-bootstrap path.
#
# Steps (idempotent): assign the project's sticky port (#374), spawn
# serve.py --bootstrap (creates board/, mines history into a one-by-one
# Haiku fly-in), wait for /health, OPEN the browser (the fly-in is gated on a
# connected viewer — sseClients>0 — so without this the cards never fly),
# install login autostart so it survives reboots, and write the global
# .onboarded marker so the picker never re-offers / a 2nd board is never
# auto-created. Adding more boards later is always explicit ("open a new
# workboard for <project>").
#
# If a board already exists for the project, we DON'T re-bootstrap — we just
# ensure the server is up and open it (open-not-recreate, per the agreed rule).
#
# Honors BOARD_NO_AUTO_OPEN=1 (skip the browser open, for headless/CI).
# Prints the resolved port on stdout.
set +e
set -u

proj_root="${1:?usage: bootstrap_project.sh <project_root>}"
hook_dir="$(cd "$(dirname "$0")" && pwd)"
serve_py="${hook_dir}/serve.py"
board_dir="${proj_root}/board"

if [ ! -f "${serve_py}" ]; then
  echo "error: serve.py not found next to bootstrap_project.sh" >&2
  exit 2
fi

# Refuse $HOME / "/" — a board there is the exact litter we're avoiding.
if [ "${proj_root}" = "${HOME}" ] || [ "${proj_root}" = "/" ]; then
  echo "error: refusing to bootstrap a board in '${proj_root}' (not a project)" >&2
  exit 2
fi

# Sticky per-project port (deterministic from board_dir; serve.py re-assigns the
# same value internally, so passing it just keeps the open-URL + autostart in sync).
want_port="$(python3 -c "import sys; sys.path.insert(0, sys.argv[2]); import port_registry as pr; print(pr.assign(sys.argv[1]))" \
  "${board_dir}" "${hook_dir}" 2>/dev/null || echo 7891)"

# Open-not-recreate: existing board → skip --bootstrap, just (re)start the server.
bootstrap_flag="--bootstrap"
[ -f "${board_dir}/board.json" ] && bootstrap_flag=""

# Already serving on its port? Then there's nothing to spawn.
if ! curl -s --max-time 0.3 "http://127.0.0.1:${want_port}/health" >/dev/null 2>&1; then
  nohup python3 "${serve_py}" --project "${proj_root}" --port "${want_port}" ${bootstrap_flag} \
    >"${proj_root}/.board-server.log" 2>&1 </dev/null &
  disown 2>/dev/null || true
  # Wait for bind + board.json (bootstrap_board writes synchronously).
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    curl -s --max-time 0.3 "http://127.0.0.1:${want_port}/health" >/dev/null 2>&1 && break
    sleep 0.4
  done
fi

# Survive reboots (the gap that silently killed servers before). Non-fatal.
python3 "${hook_dir}/install_autostart.py" --project "${proj_root}" --port "${want_port}" \
  >/dev/null 2>&1 || true

# Mark onboarded so the picker never re-offers and no 2nd board auto-spawns.
mkdir -p "${HOME}/.board-steward" 2>/dev/null
: > "${HOME}/.board-steward/.onboarded"

# Upfront fill estimate → a coffee message the caller relays to the USER. Only
# on a FRESH bootstrap (open-not-recreate has no fill running). Cheap: harvest +
# bucketize only, no haiku. Printed as a FLY_ESTIMATE: line so the announcing
# Claude can relay it; the resolved port stays the final stdout line.
if [ -n "${bootstrap_flag}" ]; then
  est="$(python3 "${hook_dir}/hourly_extractor.py" --project "${proj_root}" \
    --board "${board_dir}/board.json" --days 2 --bucket-min 30 --chunk-size 2 \
    --workers 8 --estimate-only 2>/dev/null)"
  emin="$(printf '%s' "${est}" | python3 -c "import sys,json
try:
    d=json.load(sys.stdin); m=d.get('eta_min',0)
    print(max(1,round(m)) if m and m>0.5 else (1 if d.get('chunks') else 0), d.get('chunks',0))
except Exception: print(0,0)" 2>/dev/null || echo "0 0")"
  mins="${emin%% *}"; chunks="${emin##* }"
  if [ "${mins:-0}" != "0" ]; then
    echo "FLY_ESTIMATE: Estimated time to finish: ~${mins} min. Recommended action: let the cards finish filling so you can see your pending actions."
  fi
fi

# Open the board — REQUIRED for the Haiku fly-in (it's gated on a live viewer).
# Only if nothing is already viewing it (sseClients==0), mirroring the hook.
if [ "${BOARD_NO_AUTO_OPEN:-0}" != "1" ]; then
  health="$(curl -s --max-time 0.3 "http://127.0.0.1:${want_port}/health" 2>/dev/null)"
  sse="$(echo "${health}" | python3 -c "import sys,json
try: print(int(json.load(sys.stdin).get('sseClients',0)))
except Exception: print(0)" 2>/dev/null || echo 0)"
  if [ "${sse:-0}" -eq 0 ]; then
    url="http://127.0.0.1:${want_port}"
    if command -v open >/dev/null 2>&1; then open "${url}" >/dev/null 2>&1 &
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "${url}" >/dev/null 2>&1 &
    fi
    disown 2>/dev/null || true
  fi
fi

echo "${want_port}"
