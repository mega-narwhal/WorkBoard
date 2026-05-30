# WorkBoard

A live kanban work-board for Claude Code agents and the humans they work with. The board is **the source of truth for active work** — Claude reads/writes it at session start, after every shipped task, and at session end, so nothing in a branching todo tree gets dropped.

Originally built as the `board-steward` Claude Code skill; this repo is the canonical source.

**Token cost.** ~80 tokens of skill-list description (always-on). ~130 tokens once per session for the board digest. The full `SKILL.md` (~7.7K tokens) loads only when Claude actively engages with the board. `board.json` itself (can be 130 KB+) lives on disk and is never auto-loaded — Claude queries it via `card.py` CLI primitives that return tens to a few thousand tokens per call. See [`docs/TOKEN_BUDGET.md`](docs/TOKEN_BUDGET.md) for measurements + peer benchmarks (claude-mem, mem0, letta, graphify, CLAUDE.md baseline).

## What's in the box

- `SKILL.md` — the playbook Claude follows (greet → traverse → act → log → sign off)
- `scripts/` — Python helpers (stdlib-only, no dependencies)
  - `serve.py` — local HTTP server with SSE live-streaming (no File System Access API; cross-browser). Serves `/board.json`, `/events`, `/metrics`, `/export.md`, `/export.html`, `/flash`, `/health`.
  - `card.py` — the CLI. Mutations (`add` / `move` / `fly` / `update` / `link` / `subtask` / `column` / `bug` / `improve` / `auto-ship`), reads (`digest` / `query` / `show` / `list` / `wiki` / `export` / `metrics`), and data-safety (`recover` / `migrate` / `repair-links`).
  - `_boardio.py` · `_render.py` · `_metrics.py` — shared internals (write-safety, HTML/MD renderers, velocity compute) imported by both `card.py` and `serve.py`.
  - `regen_index.py` — produces a small `index.json` digest for cheap Tier-1 reads
  - `archive_done.py` — sweeps Done cards older than 14d into monthly archives
  - `discover.py` / `discover2.py` / `hourly_extractor.py` — the **History Replay**: mine `~/.claude/projects/*/sessions/*.jsonl` and fly cards onto a fresh board so a new user opens the board and already sees their last week of work, animated in card-by-card
  - `digest_compact.py` — lossless token-cut applied to each History Replay digest before extraction (drops zero-signal boilerplate, never a file/commit/decision line)
  - `log_event.py` / `report.py` — Steward self-telemetry
  - `install_hooks.py` — wires the Claude Code hooks: `SessionStart` (board digest once per session) + `PreToolUse` (flashes a card when Claude edits a file linked to it)
  - `install_autostart.py` — **cross-platform** autostart dispatcher → delegates to `install_launchd.py` (macOS), `install_systemd.py` (Linux), or `install_taskscheduler.py` (Windows); identical flags on every OS
  - `health_check.py` — green/red dashboard verifying autostart + server + hook installed + hook fired
- `templates/`
  - `board.html` — the kanban UI (single-file, vanilla JS; Board / Calendar / Velocity views)
  - `board.json` — empty-board starter (6 default columns: Task / Backlog / In Progress / Done / Notes / Mandatory)
  - `tag-profiles.json` — 5 industry tag taxonomies (software / marketing / research / product / operations)

## Repo vs installed skill (source of truth)

board-steward lives in two places, on purpose:

| | Path | Role |
|---|---|---|
| **Dev repo** | `~/Desktop/WorkBoard/` | **Source of truth.** Git history, the live dev `board/`, the `training_data/` corpus. Edit here. |
| **Installed skill** | `~/.agents/skills/board-steward/` | The clean, standalone copy Claude Code actually loads — repo minus `.git`/`board`/`training_data`/cruft. Never edit here. |

The installed copy is kept in lockstep by **one** path — no manual `cp`:

```bash
dev/sync_skill.sh          # mirror repo → installed skill (rsync, drops dev cruft, preserves runtime telemetry/)
dev/sync_skill.sh --check  # report drift only (exit 1 if they differ)
```

`dev/install_git_hooks.sh` installs a **`post-commit`** hook that runs the sync on every commit, so the installed skill always reflects the last committed state. (`install.sh` is the separate copy-based path for end users who don't have the repo.) Run the hook installer once after cloning.

## History Replay

The **History Replay** is the onboarding demo: point it at a project's `~/.claude` chat history and it reconstructs the work as kanban cards, flying them onto a fresh empty board (`task → in-progress → done`, including real bug-bounces and improvements via `transitions[]`). It's how a brand-new user opens the board and *already* sees their last week of work instead of an empty state.

```bash
dev/simulate_install.sh --project <dir> --days N --port 7896   # run a History Replay on an isolated board
```

It is distinct from the per-card *lifecycle* walk — History Replay is the **retrospective** fill from past history; the lifecycle tracking is the **going-forward** capture as you work.

## Features

- **Zero-input auto-logging** — Claude files a card when work starts, slides it through In Progress, and writes a completion summary on ship. Idea-intent in a prompt auto-creates a card (with a 5s Undo toast); a commit auto-ships the matching card via `git log` scoring.
- **Live, animated UI** — cards pop/glide between columns over SSE as work happens. The current in-progress card pulses and pins to the top.
- **Token-efficient reads** — a progressive-disclosure ladder: `digest` (~120 tok board pulse) → `query` (sliced JSON) → `show` (one card) → `board.json` (last resort). The big file is never auto-loaded.
- **Data-safety** — cross-process `flock` + rolling backups on every write; `recover` / `migrate` / `repair-links` CLI to restore, evolve schema, and fix broken links.
- **Share + glance** — `export` to standalone HTML/Markdown for a sprint recap; a `/metrics` Velocity view (throughput, cycle time, blockers); optional bearer-token auth (`--auth-token`) to glance on your phone over the LAN.

## Quick start

```bash
cd <your-project>
python ~/Desktop/WorkBoard/scripts/serve.py --bootstrap
# creates board/ with a starter board.json + serves at http://127.0.0.1:7891

# REQUIRED — wire the Claude Code hooks (SessionStart digest + PreToolUse
# card-flash). One-time, idempotent, safe to re-run.
python ~/Desktop/WorkBoard/scripts/install_hooks.py --hook all

# RECOMMENDED — register the server to auto-start at login. Cross-platform:
# the dispatcher picks launchd (macOS) / systemd (Linux) / Task Scheduler (Windows).
# Run once per project. Pick a unique port per project (default 7891).
python ~/Desktop/WorkBoard/scripts/install_autostart.py --project $(pwd) --port 7891
```

Then either point Claude at the board (it'll invoke the skill) or open the URL in any browser.

Without the hook, the board silently drifts during long active-coding sessions — Claude forgets to invoke the skill mid-flow, and the user has to ask "did you update the board?" That question is the failure mode this skill exists to prevent.

## Verify the install

```bash
python ~/Desktop/WorkBoard/scripts/health_check.py
```

Prints a green/red dashboard checking, for every registered port:

- autostart has a live PID (server auto-starts at login — launchd/systemd/Task Scheduler)
- `/health` responds with rev + card count
- `SessionStart` hook is installed in `~/.claude/settings.json`
- Hook actually fired in the most recent Claude session (greps the session jsonl for the injection marker)

Exit code 0 only when all four pass. Add `--json` for machine-readable output.

## Why this exists

Branching todos drop items. Item 1 spawns 1.1, which spawns 1.1.1, and item 5 gets forgotten three levels deep. The board makes the full tree always-visible (subtasks inside cards) and auto-updates as work moves Backlog → In Progress → Done with per-card write-ups Claude fills in when a task ships.
