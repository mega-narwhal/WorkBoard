---
name: board-steward
description: Tracks active work in a project kanban (board.json + live HTML board served on 127.0.0.1:7891). MUST USE when user says — shipped, deployed, merged, fixed, completed, finished, verified, done, deferred, blocked, paused, moved, add card, log this, track it, what shipped, what's left, status, where are we, what did we do yesterday, sprint, backlog, todo, kanban. Also USE to STAND UP A NEW BOARD when the user says — create a new workboard, new workboard, new board, create a board, set up a board, start tracking this project, bootstrap a board (recipe → docs/BOOTSTRAP.md). Triggers — git commit / push / systemctl restart / scp / rsync that touch prod, or in-progress card whose notes match files just edited. SKIP for pure code questions (debug, explain, refactor, rename) that don't ship anything. Bootstraps on first run by mining ~/.claude/projects/*/*.jsonl for history; streams cards into an empty board with pop/slide animations. Survives sessions: SessionStart hook auto-injects a digest so the board is never forgotten between sprints, branching todos, or week-long contexts.
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Grep
  - Glob
---

# Board Steward — LIVE protocol

Keep the project's kanban synced with reality **as work happens**, so the user never has to
ask "did you update the board?" The board is **source of truth, not your memory** — when the
user asks "did we do X?", reach for `card.py` / the digest, not recall.

> **First install / bootstrapping a board, or wiring hooks & autostart?** → `docs/BOOTSTRAP.md`.
> **Fuller reference** (full `card.py` recipe sheet, auto-card-on-idea markers, tag-taxonomy rules,
> text-field detail) → `docs/PLAYBOOK.md`, read on demand. **This file is the going-forward LIVE spine.**

---

## The LIVE lifecycle — card every unit of work (the spine)

> **The card unit is the work, not the turn.** File when a *unit* starts, gets decided, or ships
> — something you/the user would later reference by `#` or grep in `git log`. One unit spans many
> turns (ask → build → review → ship) under one `#`. **Before opening:** referenced by `#` later?
> → file. Part of an existing card's life? → `subtask` / `fly`, don't open new. Clarifying intent
> before any work? → no card yet. Micro-turn ("yes", "rerun", "open the board")? → no card.

> **Granularity — a top-level card is for USER-named work, not your mechanics.** One card per unit
> the *user* asked for; your internal steps (sub-agents you spawn, exploration, a deploy/reinstall
> step, a doc tweak that ships with the change) are **subtasks of that card, or nothing** — never
> their own top-level cards. User lists 5 tasks → 5 cards; one task takes 10 internal steps → 1 card
> + subtasks, *not* 10 cards. Sub-agents follow this via the mode dial
> (`board.settings.subagentCards` / `BOARD_SUBAGENT_CARDS`): **`subtask`** (default) attaches a
> spawned agent's work to the active In-Progress card; **`collab`** (opt-in) gives agent-to-agent
> product work its own child cards under an epic; **`off`** = silent.

**`fly` is the ONLY column-change verb** — `card.py fly <num> <col>` mutates data AND asserts the
animation contract (~320ms glide + 400ms pause so chained flies don't race the browser). Side-effect
flags: `--note`, `--writeup`/`--writeup-stdin`, `--subtask`, `--bug`, `--improve`. The old `move` was
removed because it jumped. **No "want me to add a card?" prompt — just do it.**

> **Why this matters — it's the whole point, not overhead.** The board's entire value is being a
> *faithful, live mirror* of the user's work: what's in flight right now, what shipped, what's parked.
> A batched or mis-shaped card silently erases that — and the user ends up asking "did we do X?" with
> no ground truth. Getting these laws right is the single highest-leverage thing you do for the user
> here. Treat it as core to the task, and put in the effort to follow them exactly.

### The three laws (the front of the lifecycle is 100% discipline — nothing enforces it)

1. **Declare, don't record.** The card exists *and* is `fly inprogress` **before the first edit** —
   never `add`+`done` in one breath at session end. A board where every commit has a neat done-card
   can still be fully batched; that post-hoc collapse is the exact miss this kills.
2. **One pulse at a time.** Exactly one card `inprogress` (the coral halo). Many units may wait in
   Task, but only the one you're actively coding is lit. (`card.py fly … inprogress` nudges you to
   finish the active card first — #537.)
3. **The Stop hook flags batching — but only after the fact (#74).** On sign-off it checks each card
   Done this session for in-flight dwell; an `add→done` cluster with no real `inprogress` time is
   surfaced as a "batched-not-live" smell. It does **not block** — it's a mirror, not a gate.
   Declaring up front (law #1) is still 100% on you.

### Shape → pattern (LAW — every unit MUST match exactly one of these rows)

> 🔒 **ALWAYS CARD IT FIRST — then decide HOW with the table below.** Two separate steps, in order:
> **Step 1 (TIMING — always): the moment the user names more than one need, get the WHOLE set onto
> the board immediately, landing in Task — before starting *any* of the work.** Capturing is instant;
> only the *work* waits. Deferring is the bug: "remember there are N tasks" is the exact job this
> board deletes (the VISION "task 5 forgotten" case). Mixed lists too — capture the ones you'll do
> *later* NOW, not just the one you start.
> **Step 2 (SHAPE — how): only once it's all captured, decide the shape using the `Shape → pattern`
> table and header test below** — one card + subtasks if the needs share a header, else separate
> cards. Step 1 is unconditional; step 2 is where the 1-card-vs-N-cards judgment lives. (At sign-off
> a non-blocking mirror flags a possible dropped need — it counts cards **and** subtasks equally, so
> it enforces step 1 without ever pushing step 2 toward more cards; see law #3.)

> **Get the shape right and the board stays a clean, glanceable mirror for the user — this is the
> structural heart of live carding; spend the few seconds to match the row exactly.**

> **The master discriminator is THE HEADER TEST.** Before choosing a shape, ask:
> *can I write **one honest label** that covers all the parts in front of me?*
> **Yes** → parts of ONE deliverable → **one card** (parts in the title **and** as subtasks).
> **No** → independent units → **N cards, one each**.
> For a one-card unit the **title is the glance**: parts separated by ` + ` (e.g. `Column delete +
> grip drag + drag-to-trash + FLIP reorder`), each concise — **not** a vague abstract header
> (`Settle column` ❌). **Each part is also a subtask** (fuller detail) for tick-off / `N/M` progress.

| Shape | Pattern |
|---|---|
| **1. Single task** | 1 card: `add` → `fly inprogress` (before editing) → `fly done --writeup`. Title = a plain name, e.g. `Fix auth redirect` — **no ` + ` separators** (those are ONLY for multi-part cards). The atomic template the others compose from. |
| **2a. Multiple RELATED parts — one deliverable** *(passes the header test)* | **1 card + N subtasks, decomposed BEFORE inprogress.** **Title = the parts separated by ` + `** (the glance); **each part is also a subtask** (for tick-off). **Long lists** (title never exceeds **4 ` + ` segments**): ≤4 parts → flat ` + ` title; **5–16 → group** into ≤4 *named* groups of ≤4 (title = group names; items become **nested** subtasks via `subtask add <n> "<item>" --parent <gid>`); **>16 → it's a phase plan** (shape 4). Subtasks exist before `fly inprogress` (5-step order below). |
| **2b. Multiple INDEPENDENT tasks — no single header** *(fails the header test)* | **N cards** (per the up-front capture banner above — `add` ALL N into Task FIRST, before starting any). *Then* fly them `inprogress`→`done` **one at a time** (one pulse). **Don't** add-one→finish→add-next; create the whole batch first. If you can't name them with one label, they're NOT one card. |
| **3. Plan mode (multi-step plan)** | 1 **parent** card + `subtask add` per step; fly parent `inprogress`, `subtask done` at each commit, `fly done` once after final verify — *not* one done-card per step (that shows "done" while the build is half-built). |
| **4. Phase / tier plan** | **1 card PER PHASE**, tagged `phase`, title `Phase N — <goal>`, in **Task**; the phase's deliverables are its **subtasks**. The roadmap = N phase cards, glanceable. **Phase cards never go to `inprogress`** — to build a deliverable, **GRADUATE** it: `add --column task --title "<deliverable>" --link <phase#>` → `fly inprogress`; tick the phase's matching subtask when that card ships. One graduated card in flight at a time. (`card.py fly` **blocks** a `phase`-tagged card from entering inprogress and hands you the graduate command.) |
| **5. Mid-task branch** *(test: does it serve the CURRENT card's goal?)* | "Mid-task" is NOT the test — you're *always* mid-task. The test is **does resolving this serve the current card's goal?** **Yes** (a blocker you must clear to ship this card) → **subtask**, parent **stays `inprogress`**; `subtask add <n> "<finding>" --parent <sid>` the instant it trees out, *before* acting; unwind leaf-first, parent `fly done` last. **No** (e.g. doing backend, you spot an unrelated UI bug) → **NEW card** into Task, keep your one pulse on the current card, pick it up after. Use `blocked` only for an external hand-off (it drops the pulse). |

> ### 🔒 DECOMPOSE BEFORE INPROGRESS — the exact order for shapes 2a / 3 / 4
> A multi-part card's subtasks are created **while it is still in Task**, *before* it ever flies to
> `inprogress`. Decomposition is part of *starting* the card, not finishing it. Every time:
> 1. `card.py add --column task --title "<part A + part B + part C>" --origin "<their words>"`  ← parts by ` + ` (≤4 segments)
> 2. `card.py subtask add <n> "<part 1>"` … `subtask add <n> "<part N>"`  ← **decompose NOW, in Task** (nest grouped items with `--parent`)
> 3. `card.py fly <n> inprogress`  ← only **after** the subtasks exist
> 4. work each part → `card.py subtask done <n> <sid>` (card shows `1/N → 2/N → …`)
> 5. `card.py fly <n> done --writeup "…"`  ← once it reads `N/N`
>
> **HARD RULE — no naked multi-part card in IP:** never fly a multi-part card to `inprogress` with
> zero subtasks. A multi-part card arriving in IP showing only `1/1` (the auto `☑ initial ship`) is a
> LAW VIOLATION — the parts were lost. (`card.py fly … inprogress` enforces this: it blocks a
> multi-part-looking card with no subtasks unless you pass `--force`. Phase cards are the exception —
> see shape 4: they never enter IP, you graduate instead.)

### After ship
- **Regression** → `card.py fly <num> inprogress --bug "<what broke>"` — re-flies with the `bug` tag +
  a new open `🐞 fix bug: <reason>` subtask; the next `fly done` closes it (permanent cycle evidence).
- **Enhancement** → `card.py fly <num> inprogress --improve "<what's added>"` — same flow, no bug tag.

**Two layers of truth:** card **column = goal state** (is the high-level goal shipped); **subtasks =
work-cycle history** (one open-then-closed subtask per ship/bug/improve cycle). Cycle subtasks are
first-class history forever.

**ALL SUBTASKS DONE BEFORE `done` (#476).** Tick each part the moment you finish it
(`subtask done <n> <sid>`) — never narrate "done" and skip the tick. A card must read **`N/N` before
it flies to `done`**; `card.py fly … done` **blocks** a card with unfinished subtasks. A genuinely
partial ship (`shipped X/N`) is allowed — but say so with `--force`, so it's deliberate, not forgotten.

Skip the lifecycle only for genuine non-tasks (a pure question, debug-this-snippet, explain-X) per the
decision table below.

---

## Worked examples (the concrete anchor for each shape)

```bash
# SHAPE 1 — single task.  User: "fix the auth redirect bug."
card.py add --column task --title "Fix auth redirect" --origin "fix the auth redirect bug"
card.py fly <n> inprogress                       # BEFORE editing (law #1)
card.py fly <n> done --writeup "Fixed abc1234 — redirect preserves ?next. Verified on staging."

# SHAPE 2a — related parts, ONE deliverable (passes header test).
# User: "redo the column drag — reorder, drag-to-trash, and the FLIP glide."
card.py add --column task --title "Column reorder + drag-to-trash + FLIP glide" --origin "redo the column drag…"
card.py subtask add <n> "Reorder columns"        # decompose NOW, still in Task
card.py subtask add <n> "Drag-to-trash delete"
card.py subtask add <n> "FLIP glide on reorder"
card.py fly <n> inprogress                        # only AFTER subtasks exist
# ship each part → tick it:  card.py subtask done <n> s-…-1   (1/3 → 2/3 → 3/3)
card.py fly <n> done --writeup "…"                # reads 3/3

# SHAPE 2b — N INDEPENDENT tasks (fails header test).
# User: "three things: bump the version, fix the README typo, add a logout button."
card.py add --column task --title "Bump version"     --origin "…"   # add ALL THREE up front
card.py add --column task --title "Fix README typo"  --origin "…"   # so none is forgotten
card.py add --column task --title "Add logout button" --origin "…"
card.py fly <v> inprogress  …  fly <v> done          # then ONE pulse at a time
card.py fly <r> inprogress  …  fly <r> done
card.py fly <l> inprogress  …  fly <l> done

# SHAPE 4 — phase → graduate.
card.py add --column task --tag phase --title "Phase 2 — multi-board" --origin "…"
card.py subtask add <p> "Port registry"  ;  card.py subtask add <p> "Last-active pointer"
# phase NEVER goes inprogress — graduate the deliverable you're building:
card.py add --column task --title "Sticky port registry" --link <p>
card.py fly <new> inprogress  …  fly <new> done
card.py subtask done <p> <sid>                       # tick the phase's matching subtask

# SHAPE 5 — mid-task branch (on card #50).
card.py subtask add 50 "DB migration must run first" --parent s-50-2   # blocker → subtask; #50 STAYS inprogress
card.py add --column task --title "Fix tooltip clipping" --origin "spotted while doing #50"  # UNRELATED → new card, keep pulse on #50
```

---

## When to engage (decision table)

The SessionStart hook injects a digest at boot; the UserPromptSubmit hook re-injects a short protocol
reminder every turn (install via `docs/BOOTSTRAP.md` → `--hook all`). This table says when to ACT.

| User said / situation | Action |
|---|---|
| "shipped X" / "deployed Y" / "fixed Z" / "verified" / "done with N" / "landed" | **Must use** — `card.py fly <num> done --writeup "<paragraph>"` |
| "what's left?" / "status?" / "where are we?" / "what shipped today?" | **Must use** — read the digest first; `card.py list`/`query` for slices |
| "add a card for X" / "log this" / "track X" / "save for later" | **Must use** — `card.py add` |
| "move X to backlog/blocked/in-progress" / "this is deferred" / "pause X" | **Must use** — `card.py fly <num> <col>` |
| You start a substantive unit of work | **Must use — card it NOW** (`add` → `fly inprogress`), don't wait for the ship |
| Conversation just shipped something but no card moved | **Must use — backfill NOW.** Don't batch to session end (the #84/#359 drift class). |
| Main Claude just ran `git commit`/`git push`/`systemctl restart` for prod | **Must use** — a real ship; `fly <num> done --writeup "<SHA + what shipped>"` |
| User voices a deferred intent ("todo:", "remember to", "later we should", "btw can we…") | **Auto-card** — `card.py add --auto` (markers + 5 skips in `docs/PLAYBOOK.md`) |
| "debug this function" / "why is X failing?" / "explain this code" / "rename foo to bar" | **Skip** — unless the work ends in a ship/fix; then fly-card right after |
| User signals public launch (`publish`, `launch`, `go live`, `release`, `gh release`, `npm publish`, DNS go-live, repo private→public) | **Must use — gate before action.** Run `card.py prelaunch-check`; exit 9 = open items, surface verbatim + ask "OK to launch?" before any irreversible step. |
| User says urgent (`URGENT`, `ASAP`, `P0`, `BLOCKER`, `production down`, `it's broken`) | **Must use** — `card.py add` auto-detects urgency → 🚨 SUPER URGENT col, critical priority (`--urgent` forces, `--no-auto-urgent` opts out) |

**Default bias: under-engage when uncertain** — a missed card is recoverable; an over-eager skill that
interjects on every code question is noise. But once you DO act, act fully: move + writeup + index
regen + bidirectional link if there's a parent.

---

## Reconciliation — keep the board honest

Cards drift: code ships without a `fly done`; a card sits `inprogress` after the work shipped. Run a
check (don't auto-move — **surface drift, let the user confirm**; the point is the *check*):

1. **Before answering "what's left / anything else / is everything done"** — `card.py list --column
   inprogress` + `--column super-urgent`, grep recent `git log`. If a card's work is already in HEAD,
   flag it: *"#N looks shipped at <sha> — move to Done?"*
2. **After a commit cluster** with no `fly done` between — scan `git log` since the last ship; propose
   a backfill card for any uncovered scope. (`card.py auto-ship --since-ref HEAD~N` scores the match.)
3. **Before session end** — every `inprogress` card either ships now (`fly done` + writeup) or rolls
   forward with a `notes` update saying why it's still open.

The **Stop hook** is the backstop: a turn that did substantive work but ran zero `card.py` calls is
blocked at turn-end with a "card it" nudge. Don't rely on it — card as you go. (Full recon recipes →
`docs/PLAYBOOK.md`.)

---

## Saving + reading — always `card.py`

For ~95% of mutations, **don't write Python dict literals** — `card.py` handles load + mutate + `rev`
bump + `savedAt`/`savedBy='claude'` + atomic write + `index.json` regen in one shot. Run from project
root (walks up to find `board/board.json`) or pass `--board <path>`.

**Read via the progressive-disclosure ladder, cheapest first** — `digest` (~120 tok) → `query --fields …`
→ `show <num>` → `list`. Reach for the lowest rung that answers the question; reading the full
`board.json` to count columns is the anti-pattern this kills. **Full recipe sheet + the read ladder →
`docs/PLAYBOOK.md`.** Never write `index.json` by hand.

**Three text fields:** `origin` (the WHY, at creation, user's words) · `notes` (mutable, in-flight
state) · `writeup` (at Done, how-it-shipped from real SHAs). A Done card with empty `writeup` is a bug.
**Tags:** taxonomy-driven, capped, prefer an existing entry — read `board.json → tagTaxonomy` first.
(Field + tag detail → `docs/PLAYBOOK.md`.)

---

## Where the board lives

| File | Role |
|---|---|
| `board/board.json` | **Source of truth.** Read + write via `card.py`. |
| `board/index.json` | Compact digest (one line/card), auto-regenerated on every write. **Read first.** |
| `board/archive/board-YYYY-MM.json` | Done cards >14d (swept at session end). Read only when an archived `#N` is referenced. |
| `board/board.html` | Kanban UI — **don't touch**; it `fetch`es board.json from the server. |

The browser polls `GET /board.json` every 3s and reloads on `rev` change. **Before touching
`scripts/`, read the architecture tree in `VISION.md`** — new work attaches to the branch that owns
its concern or becomes a new leaf; never rewrite a parent.

---

## What you must NOT do

- **Don't wait until session end to card shipped work.** One update per unit, as it happens — batching is the drift this skill exists to kill.
- **Don't silently auto-move cards at session start.** Report drift; let the user/main-Claude confirm.
- **Don't write to `board.html`** (UI; reads `board.json` only) or **`index.json` by hand** (regen via the script).
- **Don't reuse `num` values** (always advance `nextNum`) or **break bidirectional links** (add the reverse).
- **Don't summarize away `origin`** or **fabricate `writeup`** (pull from real SHAs / evidence).
- **Don't read the full `board.json` when `index.json` / `card.py query` would do.** Pay for what you read.
