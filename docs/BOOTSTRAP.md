# Board Steward — PART 1: Bootstrap & Install (one-time)

> **This is the one-time / first-install half of the plugin.** Everything here runs
> **once** when a project first gets a board (or when wiring hooks/autostart on a new
> machine). The **going-forward LIVE protocol** — the per-turn `task → In Progress → Done`
> lifecycle you run every session — lives in `SKILL.md`. Read this file only when
> bootstrapping a board, installing hooks, or setting up autostart.

---

## Install the hooks (do this first, once per machine)

The going-forward LIVE enforcement is **hook-driven** — without the hooks, the board
silently drifts mid-session and the user has to ask "did you update the board?" (the
failure mode this skill exists to kill — card #84/#359).

```bash
python3 scripts/install_hooks.py --hook all     # RECOMMENDED — the complete set ('all' and 'live' are identical)
python3 scripts/install_hooks.py --status        # verify
python3 scripts/install_hooks.py --uninstall     # reverse (removes ALL board-steward hooks)

# After install, verify the whole stack (autostart + server + hooks installed + fired):
python3 scripts/health_check.py                  # green/red dashboard; exit 0 = all good
python3 scripts/health_check.py --json
```

`--hook all` (identical to `--hook live` — same canonical set, no ambiguity, #369) wires
**all five** hooks into `~/.claude/settings.json` (path honors `$CLAUDE_CONFIG_DIR`):

| Hook | Event | What it does |
|---|---|---|
| `hook_session_start.sh` | `SessionStart` | Injects the ~150-token board digest into context at session boot, and auto-opens the board in the browser on the first session each day (#367). |
| `hook_user_prompt.sh` | `UserPromptSubmit` | On every user message, injects the per-turn LIVE lifecycle protocol (#360). Cwd-walks for `board/board.json` — silent in non-board projects. |
| `hook_pre_tool_use.sh` | `PreToolUse` | On a file edit, flashes the matching card border coral and auto-links file→card (#102, §I below). |
| `hook_card_before_edit.sh` → `_hook_card_before_edit.py` | `PreToolUse` | **Non-blocking 'declare up front' WARN (#75).** On a file edit inside a board project with NO In-Progress card, injects a `hookSpecificOutput.additionalContext` reminder to `card.py add` → `fly inprogress` first (law #1). **Never blocks** the edit; silent when a card is already In-Progress, when editing board state files, in non-board projects, or within 60s of its last nudge (debounced). |
| `hook_stop.sh` → `_hook_stop_recon.py` | `Stop` | **Blocking backstop (#279) + batched-not-live detector (#74).** When a turn did substantive work (ship-signal OR ≥3 edits) but ran zero `card.py` calls, it emits `{"decision":"block","reason":...}` to refuse the stop so Claude cards it NOW (single-shot via the `stop_hook_active` loop guard). It also surfaces (non-blocking) any card that reached Done this session with no in-flight dwell — the batched add→done smell. Writes `board/recon_pending.json` as a deferred fallback. Silent for read-only turns / non-board projects / already-carded work. |

Other selectors: `--hook both` = session-start + user-prompt-submit only (legacy 2-hook alias);
a single hook name (`session-start` / `user-prompt-submit` / `pre-tool-use` / `card-before-edit` / `stop`)
installs just that one.

**Uninstalling.** `--uninstall` removes **all** board-steward hooks (including `card-before-edit` and
the batched detector) from `settings.json`; `--status` shows which are wired. To drop **only** the
`card-before-edit` warn while keeping the rest, re-run the installer with the set minus it — i.e.
`--hook` selection is exact-desired-state, so run each remaining hook you want, or hand-remove that one
`PreToolUse` group from `settings.json`. When installed as a plugin, `claude plugin uninstall
board-steward@workboard` removes every hook (via `hooks/hooks.json`) in one shot. `/clean-slate` wipes
all of the above plus the per-board state sidecars (`.stop_recon_state.json`, `.card_before_edit_state.json`).

The installer is **safe**: auto-backs up `settings.json` to `.bak-<ts>` before any write,
refuses malformed JSON, resolves the hook command path via `__file__` (no hardcoded
`/Users/*` — works anywhere), is a no-op when state already matches, and preserves all
other settings. Restart any open Claude Code session to pick up the change.

> The `pre-tool-use` hook (file→card flash, §I below) **is** part of the canonical
> `--hook all`/`--hook live` set. The LIVE guarantee itself comes from the Stop backstop,
> not the per-edit flash — the flash is a UX nicety on top.

### Subagent tracking — the mode dial (`#79`)

Two further hooks ship in the plugin manifest (`hooks/hooks.json`, always on with the
plugin — not in `install_hooks.py`): `PreToolUse(matcher Agent)` → `hook_subagent_spawn.sh`
and `SubagentStop` → `hook_subagent_stop.sh`, both backed by `_hook_subagent_recon.py`.
They track work done by spawned sub-agents **without the sub-agent needing to know the
protocol**. Where that work lands is the **mode dial**, resolved per board from
`BOARD_SUBAGENT_CARDS` (env) → `board.json → settings.subagentCards` → default:

| Mode | A spawned sub-agent's work becomes… | Use |
|---|---|---|
| `off` | nothing | no sub-agent tracking at all |
| `subtask` *(default)* | a **subtask of the active In-Progress card**; **nothing** if no card is in flight | normal work — internal helper/tooling agents don't pollute the board with top-level cards |
| `collab` | its **own child card linked to an epic** (`settings.subagentEpic`) | agent-to-agent product builds — the board mirrors the agent tree (epic → per-agent cards → subtasks) |

Read-only sub-agent types (`Explore`, `Plan`) are never carded in any mode. To run an
agent-to-agent build: set `settings.subagentCards: "collab"` + `settings.subagentEpic: <epic#>`
on the board (the orchestrator creates the epic first), then each collaborator's deliverable
auto-maps to a child card under it.

---

## Autostart install (cross-platform · #103)

So the board is live at `http://127.0.0.1:7891` on every login with **zero user action**
(VISION §3 "startup is instant and invisible"), one dispatcher wires the OS-native mechanism:

```bash
python3 scripts/install_autostart.py --project <dir> --port 7891   # install
python3 scripts/install_autostart.py --status                      # verify
python3 scripts/install_autostart.py --uninstall                   # reverse
python3 scripts/install_autostart.py --dry-run                     # preview the unit, write nothing (any OS)
```

`install_autostart.py` reads `sys.platform` and delegates — the recipe is identical on every OS:

| Platform | Installer | Mechanism |
|---|---|---|
| macOS (`darwin`) | `install_launchd.py` | launchd LaunchAgent (`RunAtLoad` + `KeepAlive`) |
| Linux | `install_systemd.py` | `systemd --user` service (`Restart=always`; suggests `loginctl enable-linger`) |
| Windows (`win32`) | `install_taskscheduler.py` | Task Scheduler `ONLOGON` task running `pythonw.exe` (no console window) |

All three honor the same flags, run **unprivileged** (no sudo/admin), back up any existing
unit before overwrite, and refuse a real install on the wrong OS with a pointer to the
correct installer (`--dry-run` still previews on any OS).

---

## At session start (server health)

1. **Ensure the local board server is up.** Cheap check + spawn if needed:
   ```bash
   PLUGIN=$(ls -dt ~/.claude/plugins/cache/*/board-steward/*/ 2>/dev/null | head -1)
   curl -sf http://127.0.0.1:7891/health >/dev/null 2>&1 || \
     nohup python3 "$PLUGIN/scripts/serve.py" \
       --project "$(pwd)" >/tmp/board-steward.log 2>&1 &
   sleep 0.3 && curl -sf http://127.0.0.1:7891/health | python3 -m json.tool
   ```
   Use `Bash` with `run_in_background=true` for the spawn. Print `📋 Board at http://127.0.0.1:7891`.
   If port 7891 is held by an older instance pointed at a different project, kill it
   (`lsof -ti tcp:7891 | xargs kill`) and respawn.
2. Read `board/index.json` (Tier 1). If missing → `scripts/regen_index.py board/board.json`;
   if `board.json` itself is missing → "First-time bootstrap" below.
3. Read `MEMORY.md` + today's + yesterday's `~/Desktop/conversation_history/conversation_raw_*.md`.
4. Skim last 1–2 days of conversation + `git log --oneline -20` for signals.
5. Diff reality vs board; surface drift (shipped-but-still-inprogress, un-carded work,
   forgotten subtasks, empty `origin`, broken `linkedCards`). **Do not silently apply** —
   show drift first, let the user/main-Claude confirm.

## At session end

1. Apply pending updates; add cards for new discovered work; refresh bidirectional links;
   update `notes` for in-flight items.
2. **Archive sweep:** `python3 scripts/archive_done.py board/board.json` — Done >14d → `board/archive/board-YYYY-MM.json`.
3. Regenerate `index.json` (always after a write); bump `rev` + write.

---

## Helper scripts (shipped with this plugin)

Live at the installed plugin's `scripts/` dir — resolve it with
`PLUGIN=$(ls -dt ~/.claude/plugins/cache/*/board-steward/*/ | head -1)`:

| Script | Purpose | Usage |
|---|---|---|
| `card.py` | **Default mutator** — add/update/move/fly cards, subtasks, links, columns. Auto rev-bump + index regen. POSTs to server if up (→ live SSE animation). | `python3 card.py <subcommand> ...` (see SKILL.md "Saving cleanly") |
| `serve.py` | Local HTTP server for board.html + board.json + `/events` SSE stream | `python3 serve.py [--project DIR] [--port 7891] [--bootstrap]` |
| `discover.py` | Mine `~/.claude/projects/*/*.jsonl` for card material (first/last prompts, files edited, ship/defer hints). Bootstraps the board from real history. | `python3 discover.py [--project DIR] [--days 14] [--memory]` |
| `regen_index.py` | Rebuild `index.json` from `board.json` | `python3 regen_index.py <path>/board.json` |
| `archive_done.py` | Sweep Done >14d → `archive/board-YYYY-MM.json` | `python3 archive_done.py <path>/board.json [--days 14] [--dry-run]` |
| `install_hooks.py` | Wire LIVE hooks into settings.json | `python3 install_hooks.py --hook all` |
| `install_autostart.py` | Cross-platform autostart dispatcher (#103) | `python3 install_autostart.py [--project DIR] [--port 7891] [--status] [--uninstall] [--dry-run]` |

All stdlib-only, project-agnostic, idempotent.

---

## First-time bootstrap — the "live build" install moment (the History Replay)

> **Canonical name: the History Replay.** Mining a project's past `~/.claude` chat history
> and flying the reconstructed cards onto a fresh empty board (`task → in-progress → done`,
> incl. real bug-bounces/improves). The **retrospective** backfill — distinct from the
> **going-forward** per-card lifecycle in SKILL.md. Dev harness: `dev/simulate_install.sh`.

When `board/board.json` doesn't exist yet, the install is a **show**: empty board appears,
then cards stream in one-by-one with pop animations. The user *watches their own history
materialize*. Don't shortcut this — the visible build is the value.

```bash
# 0. Resolve the installed plugin dir
PLUGIN=$(ls -dt ~/.claude/plugins/cache/*/board-steward/*/ 2>/dev/null | head -1)

# 1. Bootstrap board dir + start server in background
python3 "$PLUGIN/scripts/serve.py" --project "$(pwd)" --bootstrap >/tmp/board-steward.log 2>&1 &
sleep 0.4 && curl -sf http://127.0.0.1:7891/health | python3 -m json.tool

# 2. Open the browser — user sees empty board with default columns
open http://127.0.0.1:7891     # macOS; use xdg-open on Linux

# 3. Mine session history into a JSON context dump (no cards written yet)
python3 "$PLUGIN/scripts/discover.py" --project "$(pwd)" --days 14 --memory > /tmp/board-discover.json
```

Then **read `/tmp/board-discover.json`** (per-session first/last prompt, files edited, ship/
defer hints, MEMORY.md) and decide: what columns beyond the defaults, what 10–25 cards to
create (done = resolved shipHints, inprogress = unfinished sessions, backlog = deferHints,
ideas = "later"/"future"), and chronological order (sort by session `endedAt` ascending so
the oldest work materializes first). **Stream at 200ms pace** — one `card.py add` per Bash
call with `sleep 0.2` between — each POSTs to the server → `card-added` SSE → 320ms pop.

After the stream: say one line (*"Built 18 cards from 12 sessions over 14 days. Live at
http://127.0.0.1:7891."*); if the project has a `CONTEXT.md`, append the §18 Board protocol.
**Don't ask "should I scan your history?"** — the skill knows what to do. Only prompt if
`discover.py` returns 0 sessions AND no MEMORY.md.

### Standing up a board on request (the NL trigger)

When the user *asks* — "create a new workboard", "set up a board", "start tracking this
project" — treat it as the bootstrap above, don't make them run `install.sh` by hand:

- **For the current project** (`$(pwd)`): run the `serve.py --bootstrap` recipe above.
- **For a different/second project**: `./install.sh --project <dir>` (full install + bootstrap
  there), or `serve.py --project <dir> --bootstrap` for just the board.

**Port designation is automatic — never ask the user which port or which board.** Each project
owns a stable port for life, assigned lowest-free from **7891 upward** and persisted in
`~/.board-steward/port-assignments.json` (`port_registry.assign()`). WorkBoard keeps 7891, the
next project gets 7892, and so on — `serve.py` self-corrects at bind time so two projects passing
the same preferred port can never collide (#374). Claude picks *which* board to open from context
(the project you're working in); the user can later open another by just asking ("open the
workboard for &lt;project&gt;"), which resolves that project's designated port and opens it.

### Default columns on install

The template `board.json` ships with these columns left-to-right: `task`, `backlog`,
`inprogress`, `done`, `notes`, `ideas` (stacked under notes), `mandatory`. `serve.py` runs
an idempotent migration on load that appends any missing default cols to existing boards
(matched by id OR case-insensitive name, so a hand-named `notes` isn't duplicated). Add
others (`blocked`, `consideration`, `review`, `super-urgent`, project-specific) on demand via
`card.py column add` — only when a real card needs them. Empty columns are noise.

---

## §J — Inline extraction: process `extraction_pending.json` (#247, the FREE opt-in path)

The bootstrap default is **`--bootstrap-mode haiku`** (autonomous). When `--bootstrap-mode
inline` is chosen, `serve.py` stages the bucketed history into `<board>/extraction_pending.json`
and lets **you (main Claude)** emit the cards — free (no extra usage), no key, higher quality
than Haiku (full context). The SessionStart hook surfaces `📋 INLINE EXTRACTION PENDING` when
the file exists.

**When you see that nudge (or find the file), process it — don't ask:**

1. Read `extraction_pending.json`: `board`, `card_py`, `card_format` (exact schema + routing),
   `instructions`, `chunks` (each `label`, `bucket_ts_iso`, `digest`, newest-first). Process in
   order and **dedupe across chunks** — a multi-chunk effort is ONE card.
2. For each chunk, identify discrete units per `card_format`. Add each born in **task**, then
   **fly through its lifecycle** so it glides:
   ```bash
   python3 <card_py> --board <board> add --column task --priority PRIO \
     --title "clean title (NO code prefix)" [--code CODE] \
     --origin "the user's WHY" --notes "what/how/state; cite the SHA if a COMMIT line is in the digest" \
     --created-at <bucket_ts_iso> [--tag T]
   # done card → TWO hops (lays in In Progress); card.py auto-adds the ☑ initial-ship subtask:
   python3 <card_py> --board <board> fly <num> inprogress --pause-ms 400
   python3 <card_py> --board <board> fly <num> done --pause-ms 400 --writeup "<the notes>"
   # inprogress → one hop. backlog/mandatory/notes → leave (no fly).
   # RICHER PATH (#294) — only when the digest SHOWS it: reconstruct a real bug-bounce:
   python3 <card_py> --board <board> fly <num> inprogress --bug "<what broke>"
   python3 <card_py> --board <board> fly <num> done --writeup "<the fix>"
   # ENHANCEMENT after ship → --improve "<what's added>" instead of --bug.
   ```
3. Same quality bar as the live board: clean titles, `code` only for distinctly-named systems,
   SHA citations, distinct origin (WHY) vs notes (WHAT). Reconstruct true lifecycle; only replay
   hops the digest shows.
4. **Completeness sweep — "never miss a point" (priority: mandatory > notes > backlog).** A
   ship-oriented read drops no-marker categories. Re-scan **every** chunk digest for: 🚨
   **mandatory** (urgency the user voiced — "impt"/"must"/"urgent"/"asap"/"p0"/"blocker"/launch
   gate), 📝 **notes** (decision/rationale that isn't shippable work), **backlog** (deferred —
   "later"/"next session"/"defer", with a `⏸ OPEN — <what remains + resume trigger>` note). Add
   one card per signal that didn't already become a card. Mandatory first.
5. **Delete `extraction_pending.json`** when all chunks + the sweep are done.

**Mode decision (durable, flipped 260531):** `--bootstrap-mode haiku` is the **default** —
autonomous, no main-Claude step, runs `claude -p` in the background on the user's existing
login (NO API key); fast + robust since `MAX_THINKING_TOKENS=0` cut it ~6× and `parse_card_array`
salvages prose-wrapped output. `inline` stays an **opt-in** (free, highest quality — dedupes
multi-chunk efforts, reconstructs bounces); prefer it when a live session is present and quality
matters more than hands-off. `--bootstrap-mode discover` is the zero-LLM heuristic floor.

---

## §H — Auto-ship after every commit (#101)

`card.py auto-ship` assembles the Done writeup from `git log` instead of hand-typing it (the
failure mode where the writeup goes empty and the card drifts into Done with no SHA). It scores
inprogress cards against commit subjects (code-exact = 3pts, `#num` = 2pts, title tokens = 1pt).

```bash
python3 card.py auto-ship --since-ref HEAD~3              # scan: which cards look shipped
python3 card.py auto-ship 101 --since-ref HEAD~1          # dry-run preview (always first)
python3 card.py auto-ship 101 --since-ref HEAD~1 --apply --writeup-extra "smoke + live fire verified"
```

Discipline: scan after every commit cluster; always dry-run first; add `--writeup-extra` for what
git can't see; **score < 2 = STOP** (no confident match — don't `--force`); plain `fly done` is
still right for non-commit work (config tweak, deferral decision).

## §I — Auto-link files to cards (#102, in the canonical `--hook all` set)

When Claude edits a file a card "owns" (`card.linkedFiles`), the `pre-tool-use` hook pings
`/flash` and the card border pulses coral. Wired by the canonical `install_hooks.py --hook all`
(identical to `--hook live`).

```bash
python3 card.py update 83 --add-linked-file <abs-path> --add-linked-file <abs-path>
python3 card.py update 83 --rm-linked-file <abs-path>
```

Link tight when you start a card (after `fly inprogress`), unlink at `move done`. Don't
pre-emptively link every file a card might touch. One file → many cards OK (≤4 flashes).

---

## Card schema (full)

```json
{
  "num": 14,                            // global stable reference — "#14"
  "id": "c-fact9",                      // immutable id
  "code": "FACT9",                      // optional human badge
  "priority": "critical" | "mid" | "low" | null,
  "title": "...",
  "column": "ideas" | "backlog" | "inprogress" | "blocked" | "done" | "<custom>",
  "tags": ["..."],
  "origin": "WHY this exists — user's words, convo context, decision rationale",
  "notes": "ongoing working context (mutable as work progresses)",
  "writeup": "completion summary (multi-para; filled when done)",
  "createdAt": "<ISO>",
  "updatedAt": "<ISO>",
  "doneAt": null | "<ISO>",
  "lastTouchedSubtask": null | "<ISO>",
  "linkedCards": ["c-other-id", ...],   // bidirectional family links
  "subtasks": [{"id","text","done","collapsed","children":[<recursive>]}]
}
```

Root fields: `rev`, `savedAt`, `savedBy`, `nextNum`, `schemaVersion`, `columns`, `cards`,
`tagTaxonomy`. New card → `num = state.nextNum`, then `nextNum += 1`. New `linkedCards` entry →
add the reverse on the other card (bidirectional).

## index.json schema (Tier 1 — what you read first)

Auto-generated (don't hand-edit). One entry per card, short keys for density:

```json
{
  "rev": 36, "generatedAt": "<ISO>", "totalCards": 65,
  "columns": [{"id": "backlog", "count": 34}, ...],
  "cards": [
    { "n": 14, "id": "c-fact9", "code": "FACT9", "title": "...", "col": "done",
      "prio": "mid", "upd": "<ISO>", "done": "<ISO or null>", "tags": ["..."],
      "p": "5/7", "links": 3, "origin": "first 140 chars, snippet only" }
  ]
}
```

A 65-card index ≈30KB; 200-card ≈90KB. `board.json` scales with notes/writeups/subtasks (50KB+ at 65 cards).

---

## Telemetry (optional self-grading)

`scripts/log_event.py` appends one JSON event per run to the fixed home path
`~/.board-steward/telemetry/events.jsonl` (override `BOARD_TELEMETRY_FILE`) — trigger, reads, writes, drift,
est_tokens, issues, notes). It's how the skill self-grades — inspect with
`python3 scripts/report.py [--days 7]`. Optional; not part of the per-turn LIVE loop.

## Traversal — 4 file tiers (read cheaply)

| Tier | File | When |
|---|---|---|
| 1 — Always | `board/index.json` | Every invocation. Whole-board snapshot, compact. |
| 2 — Recent | `board/board.json` (filter last 7d by `updatedAt`) | Full notes/subtasks for active work. |
| 3 — Older | `board/board.json` (one card by `num`) | User references `#N` for an older card — read just its `origin`+`writeup` via Grep. |
| 4 — Archived | `board/archive/board-YYYY-MM.json` | Only when a `#N` from that period is referenced. |

In a live session you rarely read files directly — use the `card.py` progressive-disclosure
ladder (`digest` → `query` → `show` → `board.json`), see SKILL.md "Saving cleanly".
