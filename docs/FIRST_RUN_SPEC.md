# Board Steward — FIRST-RUN SPEC (install → discover → picker → fly-in)

> The canonical first-run experience, so it stops getting re-litigated. This is the
> path from `/plugin install` to a live board flying in its history. The per-turn
> LIVE lifecycle lives in `SKILL.md`; the one-time install mechanics live in
> `BOOTSTRAP.md`. This file is the **glue**: what fires, in what order, and why.

---

## The one fact that shapes everything

`/plugin install board-steward@workboard` only **registers** the plugin (copies
files, wires hooks). It cannot run discover / ask / fly — those are the plugin's
*own* code, which only runs through a **hook** or an **explicit invocation**. So the
first-run flow hangs off the **SessionStart hook**, which hands off to **Claude** to
draw the picker (a hook can emit text but cannot call AskUserQuestion).

---

## The flow

```
INSTALL (one time)
  /plugin marketplace add ~/Desktop/WorkBoard
  /plugin install board-steward@workboard      → "✓ Installed"
  /reload-plugins                               (registers hooks; NO board yet — correct)

NEXT SESSION START  (hook_session_start.sh)
  • board found by cwd-walk?  → render it (digest + idempotent open). Done.
  • else, in $HOME / "/" and NOT yet .onboarded:
      1. run  discover2.py --list-projects --top 5 --days 3 --format lines
         - content-based (session cwds), NOT a filesystem walk
         - 3-day window: cheap on every $HOME session, surfaces what's active now
         - ranked by SUBSTANCE (sessions·10 + edits·2 + prompts + recency·15)
         - child cwds FOLDED into nearest tracked ancestor (no git-walk)
         - $HOME / Desktop / /tmp subtrees excluded
      2. emit <board-steward-session-start> handoff →
         CLAUDE draws AskUserQuestion (one option per project; tappable on
         desktop / phone / remote-control). Headless fallback = numbered text.
      3. user picks ONE project at PATH →
         CLAUDE runs:  bash <hook_dir>/bootstrap_project.sh "PATH"
            → sticky port → serve.py --bootstrap → OPEN browser
              (fly-in is viewer-gated) → autostart → write .onboarded
            → History Replay flies the project's cards in one-by-one (Haiku)

LATER
  • Exactly ONE board auto-created. Add another explicitly:
      "open a new workboard for <project>"  → discover→pick→fly again
  • Re-offer: the picker re-appears every $HOME session UNTIL the first board
    exists (.onboarded). It is NOT a one-shot — that bug (the old
    .home-hint-shown gate) is why the offer used to vanish on session 2.
```

---

## Idempotent open — "only open if no WB is rendered" (already shipped 6/2)

Every session start, for the project's **sticky port**, the hook applies one rule
(handles both the post-install replay and every later live session — same code):

| State | Signal | Action |
|---|---|---|
| No server on the port | `/health` unreachable | spawn `serve.py` + open a tab |
| Server up, no tab | `/health` `sseClients == 0` | open exactly one tab (reuse server) |
| Server up, tab open | `/health` `sseClients > 0` | **do nothing** (no tab-spam) |

A 10s `.spawn.lock` prevents two quick sessions from double-spawning. The
`.onboarded` marker + sticky port (`port_registry.assign`) guarantee a new session
**never** auto-creates a second board.

---

## Rendering this on a phone / remote-control

The native AskUserQuestion picker renders as **tappable buttons** on desktop, web,
mobile, and `/remote-control` alike — no difference. A numbered text list also works
everywhere (you type the number). The only constraint: the **native** picker must be
drawn by Claude (the agent), which is exactly why the hook hands off rather than
trying to draw it itself.

---

## Files

| File | Role |
|---|---|
| `scripts/hook_session_start.sh` | SessionStart: cwd-walk render, else home-dir discover→picker handoff |
| `scripts/discover2.py` `--list-projects` | content-based enumerate + substance rank + fold + `--top N` |
| `scripts/bootstrap_project.sh` | the picker's single entrypoint: port → bootstrap → open → autostart → `.onboarded` |
| `scripts/port_registry.py` | sticky per-project port (`assign`) |
| `dev/discover.py` | archived legacy engine (reachable only via `--legacy`) |

---

## Known caveats

- **Fold targets the shallowest ancestor.** If you've run sessions at both
  `~/Desktop/QuantifyMe` and `…/QuantifyMe/HFTAgents`, HFTAgents folds **up** into
  QuantifyMe, so the picker offers "QuantifyMe" and bootstraps at
  `~/Desktop/QuantifyMe/board` — not the established `…/HFTAgents/board`. This is the
  cost of fold-into-parent (git-root grouping was declined). Workaround: type the
  exact path at the picker.
- `~/.claude/projects` can surface as a candidate (real edits happen there). Add it
  to `_NON_PROJECT_PREFIXES` in `discover2.py` if it's unwanted.

---

## Verify (end-to-end rehearsal)

```bash
# enumerate is clean (no subdirs / $HOME / tmp; score + more present)
python3 scripts/discover2.py --list-projects --top 5 --days 3

# legacy still runs from its archived home
python3 scripts/discover2.py --legacy --project ~/Desktop/WorkBoard --days 1

# bootstrap refuses $HOME
bash scripts/bootstrap_project.sh "$HOME"        # → exit 2

# FULL first-run: clear the marker, start Claude in $HOME →
#   picker handoff → pick → bootstrap_project.sh → browser opens → cards fly →
#   .onboarded written → 2nd $HOME session is silent (no re-offer, no 2nd board) →
#   close tab, reopen project session → server reused, one tab re-opened.
rm -f ~/.board-steward/.onboarded
```
