# Changelog

All notable changes to WorkBoard / the `board-steward` skill.

The format follows [Keep a Changelog](https://keepachangelog.com/); this project
uses date-stamped pre-1.0 development entries until the first tagged release.

## [Unreleased]

Pre-release hardening toward `v1.0.0-rc.1`. Built across Plan v2 phases 0–6.

### Added — auto-logging (Phase 3, the VISION "zero-input" promise)
- **Auto-card on idea-intent** (`#100`) — `card.py add --auto`; deferred-intent
  markers in a prompt create a card with a 5-second Undo toast.
- **Auto-ship after commit** (`#101`) — `card.py auto-ship` scores In-Progress
  cards against `git log` and writes the completion summary from matched commits.
- **Auto-link files to cards** (`#102`) — a `PreToolUse` hook flashes a card on
  the board when Claude edits a file linked to it (`/flash` SSE endpoint).

### Added — data-safety (Phase 3.5)
- Cross-process `flock` + rolling backups on every write (`_boardio.py`).
- `card.py recover` — list / restore rolling backups (validated, reversible).
- `card.py migrate` — idempotent, `schemaVersion`-driven schema migrations.
- `card.py repair-links` — fix dangling / self / duplicate / one-sided links.

### Added — cross-platform autostart (Phase 4)
- `install_autostart.py` dispatcher → `install_launchd.py` (macOS),
  `install_systemd.py` (Linux), `install_taskscheduler.py` (Windows). Identical
  flags on every OS; unprivileged; refuses a real install on the wrong OS.

### Added — token-efficiency read tier (Phase 5)
- `card.py digest [--json]` — ~120-token board pulse on demand.
- `card.py query` — sliced JSON; `--fields` projection, `--since-days`, `--limit`.
- `card.py wiki` — narrative Markdown render.
- SKILL.md documents the `digest → query → show → board.json` ladder.

### Added — scale + share (Phase 5.5)
- **Export** (`#115`) — `card.py export` and `serve.py /export.md` / `/export.html`
  produce a standalone, no-JS sprint snapshot. Shared renderer in `_render.py`.
- **Velocity metrics** (`#114`) — `serve.py /metrics?since=Nd`, `card.py metrics`,
  and a Velocity tab in the UI (throughput, cycle time, blockers, priority drift).
- **LAN access + auth** (`#116`) — `serve.py --auth-token`; bearer token via
  `Authorization` / `?t=` / cookie, constant-time compare; prints a scan-me LAN
  URL. `card.py` carries `$BOARD_AUTH_TOKEN` on its writes.

### Pending before `v1.0.0-rc.1`
- `#113` lazy-render + incremental SSE diff for 500+ card boards (Phase 5.5, deferred).
- `#112`/`#245` full-text / Cmd+K search.
- `#247` inline hourly transition extractor.

## [0.1.0] — 2026-05-26
- Initial commit — WorkBoard kanban skill extracted from `board-steward`:
  live SSE board (`serve.py` + `board.html`), `card.py` CLI, `index.json`
  digest, archive sweep, history bootstrap (`discover.py`), SessionStart hook,
  launchd autostart, self-telemetry.
