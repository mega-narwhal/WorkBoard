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

> **First install / bootstrapping a new board, or wiring hooks & autostart?** → see
> `docs/BOOTSTRAP.md` (the one-time PART 1). This file is the **going-forward LIVE** half.

---

## The LIVE lifecycle — card every unit of work (the spine)

> **The card unit is the work, not the turn.** File a card when a *unit of work* starts, gets
> decided, or ships — where a unit is something a future you (or the user) would reference by
> `#` or grep for in `git log`. One unit usually spans many turns (ask → ask back → build →
> review → ship), all under one `#`. One turn produces *many* cards only when the user names
> many distinct units.
>
> **Before opening a card, test:** *Will I/the user reference this by `#` later?* → file. *Part
> of an existing card's lifecycle?* → `subtask add` / `fly`, don't open a new one. *Clarifying
> intent before any work?* → no card yet; open when work starts. *Conversational micro-turn
> ("yes", "stop", "rerun", "open the board")?* → no card.

When the user gives a substantive task, drive its card through these stages — **no "want me to
add a card?" prompt, just do it.** Use **`fly`** for every cross-column hop: `card.py fly <num>
<col>` mutates data AND asserts the animation contract (~320ms glide + 400ms pause so chained
flies don't race the browser). It takes side-effect flags (`--bug`, `--improve`, `--subtask`,
`--note`, `--writeup`/`--writeup-stdin`). **`fly` is the ONLY column-change verb** — the old
`move` was removed because it jumped (mutated data with no animation); a card must never jump.

1. **On receipt** — `card.py add --column task --title "<verb + noun>" --priority <c|m|l> --origin "<user's exact phrasing>"`. Card pops into Task.
2. **On start** — `card.py fly <num> inprogress` the moment work begins. Coral active-work halo pulses.
3. **On scope expansion / new finding mid-task** — `card.py subtask add <num> "<the new step>"`. Subtasks tree out *inside* the card; the parent never leaves In Progress while children pend.
4. **On a transient blocker** — `card.py fly <num> blocked --note "<reason>"`. Fly back to `inprogress` when unblocked.
5. **On ship** — `card.py fly <num> done --writeup "<paragraph: commits, files, verification>"`. Card glides to the top of Done's today-group.
6. **On regression after ship** — `card.py fly <num> inprogress --bug "<what broke>"`. Flies back with the `bug` tag + a new open `🐞 fix bug: <reason>` subtask; the next `fly done` closes it, leaving permanent evidence of the cycle.
7. **On enhancement after ship** — `card.py fly <num> inprogress --improve "<what's added>"`. Same flow, no bug tag.

**Two layers of truth:** card **column = goal state** (is the high-level goal shipped); **subtasks
= work-cycle history** (one open-then-closed subtask per ship/bug/improve cycle — `☑ initial ship`
on first done, `🐞 fix bug: …` on each reopen). A Done card with open subtasks is a deliberate
"shipped 1/5" — leave it. Cycle subtasks are first-class history forever.

This is the zero-input headline behaviour from `VISION.md` §"The principle". Skip the lifecycle
only for genuine non-tasks (a pure question, debug-this-snippet, explain-X) per the table below.

---

## When to engage (decision table)

The SessionStart hook injects a digest at boot, and the UserPromptSubmit hook re-injects this
protocol every turn (install via `docs/BOOTSTRAP.md` → `--hook all`). This table says when to ACT.

| User said / situation | Action |
|---|---|
| "shipped X" / "deployed Y" / "fixed Z" / "verified" / "done with N" / "landed" | **Must use** — `card.py fly <num> done --writeup "<paragraph>"` |
| "what's left?" / "status?" / "where are we?" / "what shipped today?" | **Must use** — read the digest first; `card.py list`/`query` for slices |
| "add a card for X" / "log this" / "track X" / "save for later" | **Must use** — `card.py add` |
| "move X to backlog/blocked/in-progress" / "this is deferred" / "pause X" | **Must use** — `card.py fly <num> <col>` |
| You start a substantive unit of work | **Must use — card it NOW** (`add` → `fly inprogress`), don't wait for the ship |
| Conversation just shipped something but no card moved | **Must use — backfill NOW.** Don't batch to session end (the #84/#359 drift class). |
| Main Claude just ran `git commit`/`git push`/`systemctl restart` for prod | **Must use** — a real ship; `fly <num> done --writeup "<SHA + what shipped>"` |
| "debug this function" / "why is X failing?" / "explain this code" | **Skip** — board not relevant |
| "rename foo to bar" / pure code edits | **Skip — unless** the work ends in a ship/fix; then fly-card right after |
| User signals public launch (`publish`, `launch`, `go live`, `release`, `make public`, `gh release`, `npm publish`, DNS go-live, repo private→public) | **Must use — gate before action.** Run `card.py prelaunch-check`. Exit 9 = open items; surface them verbatim and ask "OK to launch?" before any irreversible step. |
| User says urgent (`URGENT`, `ASAP`, `P0`, `BLOCKER`, `production down`, `critical bug!`, `it's broken`) | **Must use** — `card.py add` (auto-detects urgency → 🚨 SUPER URGENT col, critical priority). `--urgent` forces, `--no-auto-urgent` opts out. |

**Default bias:** under-engage when uncertain — a missed card is recoverable; an over-eager
skill that interjects on every code question is noise. But once you DO act, act fully: move +
writeup + index regen + bidirectional link if there's a parent.

---

## Reconciliation — keep the board honest

Cards drift: code ships without a `fly done`; commits land that should've been a card; a card
sits `inprogress` after the work shipped. Run a reconciliation pass:

1. **Before answering "what's left / anything else / is everything done"** — run
   `card.py list --column inprogress` + `--column super-urgent`, then grep recent `git log` for
   matching commits. If a card's work is already in HEAD, flag it: *"#N looks shipped at <sha> —
   move to Done?"*
2. **After a commit cluster** with no `fly done` between — scan `git log` since the last ship;
   propose a backfill card for any scope no card covers. (`card.py auto-ship --since-ref HEAD~N`
   scores the match — see `docs/BOOTSTRAP.md` §H.)
3. **Before session end** — every `inprogress` card either ships now (`fly done` + writeup) or
   rolls forward with a `notes` update saying why it's still open.

**Don't silently auto-move cards** — surface drift, let the user confirm. The point is the
*check*, not the *move* (auto-moving re-introduces the silent-drift class).

```bash
python3 ~/.agents/skills/board-steward/scripts/card.py list --column inprogress
git log --oneline --since="$(date -v-2H +%FT%T)"     # commits in the last 2h — anything un-carded?
```

The **Stop hook** is the backstop here: if a turn did substantive work but ran zero `card.py`
calls, it blocks the turn-end and tells you to card it (install via `--hook all`). Don't rely
on it — card as you go — but it's the safety net.

---

## Auto-card on idea-intent (the zero-input promise · #100)

When the user voices a deferred intent that isn't this turn's task, a card materialises on its
own — no "want me to add that?" prompt. The board pops a 5s Undo toast for false positives.

**Fire `card.py add --auto` when the prompt contains a deferred-intent marker** (case-insensitive,
clause-start): `I have an idea[:.]` / `idea[:.]`, `todo[:.]`, `remember to`, `note to self`,
`later we should` / `we should also` / `we'll need to`, `btw can we/could you/should we`,
`what if we` (only if paired with a deferred verb).

```bash
python3 ~/.agents/skills/board-steward/scripts/card.py add \
  --title "<deferred verb-phrase, ≤70 chars>" --auto \
  --auto-source "<the verbatim marker>" --origin "<user's full quoted sentence>"
```

`--auto` defaults `--column` to `💡 Ideas` (creates if missing) and stamps `meta.autoCreated`
(→ Undo toast). **5 hard skips** (guard the over-eager class): (1) they're asking you to do it
*now* this turn — it's the task, not a card; (2) <20 chars after the marker; (3) already an open
card (grep first); (4) recapping/quoting prior convo; (5) `nvm`/`wait`/`actually` in this or the
next 1–2 turns → roll it back. **Under-engage when uncertain** — a missed auto-card is
recoverable; an over-eager one eats trust. Ambiguous marker (`what if we`) → don't fire.

---

## Saving cleanly — always `card.py`

For ~95% of mutations, **don't write Python dict literals** — use `card.py` (handles load +
mutate + `rev` bump + `savedAt`/`savedBy='claude'` + atomic write + `index.json` regen in one
shot). Run from project root (it walks up to find `board/board.json`) or pass `--board <path>`.

```bash
card.py add --code FOO --column task --priority mid --title "..." --origin "..." --link 14
card.py update 32 --priority critical --add-tag urgent
card.py fly 32 done --writeup "Shipped abc1234. Verified on prod (...)."
card.py fly 32 inprogress --bug "drag froze on iPhone"        # reopen w/ 🐞 subtask
card.py subtask add 32 "Eyeball in Safari"   ·   card.py subtask done 32 s-foo-1
card.py link 32 14   ·   card.py unlink 32 14
card.py column add consideration "Consideration" --kind blocked --at 3

# read / filter — progressive-disclosure ladder, cheapest first (pay for what you read):
card.py digest                                    # board pulse, ~120 tok
card.py query --column inprogress --fields num,title    # sliced JSON, only the fields you ask
card.py query --since-days 1 --fields n,code,col        # recently-touched, compact
card.py show 32                                   # one full card (notes, subtasks, writeup, history)
card.py list --column inprogress --priority critical     # human-readable text view
```

**Reach for the lowest rung that answers the question.** "How many open?" → `digest`. "Which
in-progress touched perf?" → `query --column inprogress --tag perf`. "Writeup on #103?" → `show
103`. Reading the full `board.json` to count columns is the anti-pattern this ladder kills.

**Live streaming:** when `serve.py` is up on `127.0.0.1:7891`, every `card.py` call POSTs the new
state → SSE → the browser animates the change. Server down → direct file write, same end state, no
animation. `BOARD_NO_SERVER=1` forces the fallback for batch ops.

For bulk migrations / multi-card transactions / schema surgery only, the raw dict-literal recipe
+ `regen_index.py` is in `docs/BOOTSTRAP.md`. **Never write `index.json` by hand.**

---

## Three text fields — keep them distinct

| Field | When written | What it captures |
|---|---|---|
| **`origin`** | At creation | The WHY. User's words, what triggered it, decision rationale. Don't summarize away. |
| **`notes`** | Ongoing | Current state, in-flight decisions, file paths, commits being tracked. Mutable. |
| **`writeup`** | At Done | The multi-paragraph "how it shipped" — commits, verification, follow-ups. |

A Done card with empty `writeup` is a bug — fill it. Pull writeups from real SHAs / verification
evidence; if you don't have it, ask main Claude. Don't fabricate.

---

## Tag discipline (taxonomy-driven, capped)

The board carries a tag taxonomy at `board.json` → `tagTaxonomy` (max 10 main + 15 sub, each with
a colour). **Read it before tagging** and prefer an existing entry (case-insensitive) — if `bug`
exists, never invent `bugs`/`defect`/`regression-bug`. Use **main** for work type (bug / feature /
infra / security / perf / ui / docs / refactor), **sub** for status/modifier (shipped / deferred /
discuss-first / stress-test / verify / dependency / breaking). Project nouns (`server-g`, `fact9`)
are fine as custom tags (auto-coloured) — but check for a near-synonym first. **Never strip a tag
silently** — ask before retiring one. (Profiles + full rules: `templates/tag-profiles.json`.)

---

## Where the board lives

| File | Role |
|---|---|
| `board/board.json` | **Source of truth.** Read + write via `card.py`. |
| `board/index.json` | Compact digest (one line/card), auto-regenerated on every write. **Read first.** |
| `board/archive/board-YYYY-MM.json` | Done cards >14d (swept at session end). Read only when an archived `#N` is referenced. |
| `board/board.html` | Kanban UI — **don't touch**; it `fetch`es board.json from the server. |

The browser polls `GET /board.json` every 3s and reloads on `rev` change, flashing changed cards
green. v3 works in any browser (one Python process on `127.0.0.1:7891`). **Before touching
`scripts/`, read the architecture tree in `VISION.md`** — new work attaches to the branch that
owns its concern or becomes a new leaf; never rewrite a parent.

---

## What you must NOT do

- **Don't wait until session end to card shipped work.** One update per unit, as it happens — batching is the drift this skill exists to kill.
- **Don't silently auto-move cards at session start.** Report drift; let the user/main-Claude confirm.
- **Don't write to `board.html`** (UI; reads from `board.json` only) or **`index.json` by hand** (regen via the script).
- **Don't reuse `num` values** (always advance `nextNum`) or **break bidirectional links** (add the reverse).
- **Don't summarize away `origin`** (the user's words / historical why) or **fabricate `writeup`** (pull from real SHAs / evidence).
- **Don't read the full `board.json` when `index.json` / `card.py query` would do.** Pay for what you read.
- **Don't write inline dict literals when `card.py` works** — only for bulk migrations / multi-card transactions / schema changes.
