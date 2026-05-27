# WorkBoard

A live kanban work-board for Claude Code agents and the humans they work with. The board is **the source of truth for active work** — Claude reads/writes it at session start, after every shipped task, and at session end, so nothing in a branching todo tree gets dropped.

Originally built as the `board-steward` Claude Code skill; this repo is the canonical source.

## What's in the box

- `SKILL.md` — the playbook Claude follows (greet → traverse → act → log → sign off)
- `scripts/` — Python helpers
  - `serve.py` — local HTTP server with SSE live-streaming (no File System Access API; cross-browser)
  - `card.py` — one-line CLI for card add / move / update / link / subtask / column ops
  - `regen_index.py` — produces a small `index.json` digest for cheap Tier-1 reads
  - `archive_done.py` — sweeps Done cards older than 14d into monthly archives
  - `discover.py` — mines `~/.claude/projects/*/sessions/*.jsonl` to bootstrap a board from prior chat history
  - `log_event.py` / `report.py` — Steward self-telemetry
  - `install_hooks.py` / `hook_session_start.sh` — wires a Claude Code SessionStart hook that injects a board digest once per session
  - `install_launchd.py` — registers the server as a launchd job so it auto-starts at login (macOS)
  - `health_check.py` — green/red dashboard verifying launchd + server + hook installed + hook fired
- `templates/`
  - `board.html` — the kanban UI (single-file, vanilla JS)
  - `board.json` — empty-board starter (4 default columns: Ideas / Backlog / In Progress / Done)
  - `tag-profiles.json` — 5 industry tag taxonomies (software / marketing / research / product / operations)

## Quick start

```bash
cd <your-project>
python ~/Desktop/WorkBoard/scripts/serve.py --bootstrap
# creates board/ with a starter board.json + serves at http://127.0.0.1:7891

# REQUIRED — wire the SessionStart hook so Claude sees the board digest
# at the top of every new session. One-time, idempotent, safe to re-run.
python ~/Desktop/WorkBoard/scripts/install_hooks.py

# RECOMMENDED — register the server with launchd so it auto-starts at login
# (macOS). Run once per project. Pick a unique port per project (default 7891).
python ~/Desktop/WorkBoard/scripts/install_launchd.py --project $(pwd) --port 7891
```

Then either point Claude at the board (it'll invoke the skill) or open the URL in any browser.

Without the hook, the board silently drifts during long active-coding sessions — Claude forgets to invoke the skill mid-flow, and the user has to ask "did you update the board?" That question is the failure mode this skill exists to prevent.

## Verify the install

```bash
python ~/Desktop/WorkBoard/scripts/health_check.py
```

Prints a green/red dashboard checking, for every registered port:

- launchd has a live PID (server auto-starts at login)
- `/health` responds with rev + card count
- `SessionStart` hook is installed in `~/.claude/settings.json`
- Hook actually fired in the most recent Claude session (greps the session jsonl for the injection marker)

Exit code 0 only when all four pass. Add `--json` for machine-readable output.

## Why this exists

Branching todos drop items. Item 1 spawns 1.1, which spawns 1.1.1, and item 5 gets forgotten three levels deep. The board makes the full tree always-visible (subtasks inside cards) and auto-updates as work moves Backlog → In Progress → Done with per-card write-ups Claude fills in when a task ships.
