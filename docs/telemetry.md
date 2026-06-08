# Board Steward — self-tracking telemetry

Every Steward invocation appends one JSON line to `events.jsonl` — at the fixed
home path `~/.board-steward/telemetry/events.jsonl` (override with
`BOARD_TELEMETRY_FILE`) — so the skill can be **graded honestly** later instead
of from memory.

**Goal:** answer "where is the Steward struggling?" 2-3 days from now. Pain notes + issue tags are the gold; counts are context.

## Inspect

```bash
# Scripts live in the installed plugin — resolve its dir once:
PLUGIN=$(ls -dt ~/.claude/plugins/cache/*/board-steward/*/ 2>/dev/null | head -1)

# Full markdown report
python3 "$PLUGIN/scripts/report.py"

# Last week only
python3 "$PLUGIN/scripts/report.py" --days 7

# Filter to one project's board
python3 "$PLUGIN/scripts/report.py" --project /Users/malco/Desktop/QuantifyMe/HFTAgents/board

# Raw JSON (pipe to jq for ad-hoc queries)
python3 "$PLUGIN/scripts/report.py" --json
```

## Event schema

```jsonc
{
  "ts": "2026-05-26T12:55:00Z",           // ISO UTC; auto-filled if missing
  "trigger": "session-start",              // session-start | after-ship | session-end | manual | trigger-keyword:<kw>
  "project": "/path/to/board",             // absolute path to the board/ dir
  "board_rev": 37,
  "board_cards": 65,
  "reads": ["index"],                      // "index" | "board" | "archive:YYYY-MM"
  "writes": {
    "cards_moved": 0,                      // column changes
    "cards_added": 0,                      // new cards
    "subtasks_changed": 0,                 // any subtask toggle/edit/add/delete
    "writeups_filled": 0                   // Done cards with writeup filled this turn
  },
  "drift_flagged": 0,                      // items surfaced as drift
  "drift_applied": 0,                      // drift items applied this same session
  "bookends": {"greeted": true, "signed_off": true},
  "issues": [],                            // known tags — see below
  "notes": ""                              // free-form pain / observation
}
```

## Known issue tags (use these so `report.py` can count + rank)

| Tag | Meaning |
|---|---|
| `missed-greeting` | Forgot the 👋 first-line greeting |
| `missed-signoff` | Forgot the 🪪 last-line signoff |
| `read-full-when-index-enough` | Loaded `board.json` when `index.json` would have answered |
| `asked-permission-for-mandatory` | Said "want me to…" for something §3/§18 mandates |
| `drift-not-detected` | User had to point out work that should have been carded |
| `writeup-incomplete` | Moved a card to Done without a real writeup |
| `trigger-keyword-missed` | A trigger keyword fired but Steward wasn't invoked |
| `schema-confusion` | Got a board.json field wrong (linkedCards reverse missing, etc.) |
| `hook-misfire` | The optional hook fired when it shouldn't (or didn't when it should) |

**Add new tags freely** — they show up in the next report automatically.

## How the Steward logs

End of every invocation (after signoff), the Steward calls:

```bash
cat <<'EOF' | python3 "$PLUGIN/scripts/log_event.py"
{"trigger":"session-start","project":"/path/board","board_rev":37,"board_cards":65,
 "reads":["index"],"writes":{"cards_moved":0,"cards_added":0,"subtasks_changed":0,"writeups_filled":0},
 "drift_flagged":3,"drift_applied":0,"bookends":{"greeted":true,"signed_off":true},
 "issues":[],"notes":"index lacked subtask progress — had to expand for #2"}
EOF
```

If the call fails (e.g. python missing), the Steward continues — telemetry is **best-effort**, not load-bearing. But missing log lines themselves become a signal: a long gap in `events.jsonl` = Steward stopped running.

## Privacy / portability

- File is **append-only**. Never deleted by the skill.
- Lives in the plugin dir, not per-project — so the metrics travel with the plugin.
- To partition by project, use `--project <path>` on report.py (events carry the `project` field).
- Manually rotate with `mv events.jsonl events.YYYY-MM.jsonl && touch events.jsonl`.

## Improvement loop

Every 1-2 weeks, run `report.py --days 14` and look for:

1. **Issue tags ranked top-3** — fix those first (edit SKILL.md or scripts).
2. **Bookend compliance < 100%** — strengthen the mandate in SKILL.md.
3. **Read efficiency low** — index schema is missing fields; widen it in `regen_index.py`.
4. **Pain notes** — patterns across notes are usually unspoken protocol gaps.

Each improvement should result in fewer issue tags in the next 2-week window. If not, the fix didn't actually address the root cause.
