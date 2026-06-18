# Token-Efficiency Summary — WorkBoard vs mem0 · claude-mem · Letta · graphify

A neutral compilation of the four head-to-head studies in this directory. Every
number is from each study's own auto-generated reports (same tokenizer —
`tiktoken cl100k` — for every system; medium corpus = 933 real Claude-Code
sessions). Peers are measured/modeled from their **own** published numbers, with
settings that **favor the peer**, so WorkBoard's margins are conservative floors.

> Per-study detail: [`mem0-comparison/`](mem0-comparison/) ·
> [`claude-mem/`](claude-mem/) · [`letta-comparison/`](letta-comparison/) (Letta).

---

## The one-liners

- **WorkBoard builds its memory with ~98–99% fewer tokens** than mem0 and claude-mem
  (it filters deterministically before spending any model tokens).
- **WorkBoard persists work for free** — **0 model calls/session** vs an LLM
  extraction/compression call *every session* for mem0 and claude-mem.
- **Over a project's life, WorkBoard runs the memory loop 34–81% cheaper** than the
  three memory systems.
- **Honest:** on a *single* lookup, mem0 and Letta are actually *leaner* than
  WorkBoard; WorkBoard wins the **loop**, not the **lookup**. And graphify is a
  different-domain tool (code graph), included only as a calibration.

---

## Headline scoreboard

| Peer | What it is | WorkBoard's headline advantage | Where the peer wins |
|---|---|---|---|
| **mem0** | vector memory (LLM extracts facts → Qdrant) | **Live loop 33.7% fewer** tokens · **build 98.7% fewer** · persists **free** | leaner per single recall (1,800 vs 2,399); no per-turn tax |
| **claude-mem** | vector memory (Chroma; compresses each session) | **Live loop 52.6% fewer** · **build ~99% fewer** · **recall 25.9% lighter** (wins 16/19) | tight single-fact pinpoints + off-board facts |
| **Letta** (MemGPT) | in-context memory blocks re-sent **every turn** | **Live loop 81.0% fewer** (92.2% trimmed) · **no in-context memory tax** | leaner per single recall (1,064 vs 2,399) |
| **graphify** *(graphifyy 0.8.41, real install)* | **code** knowledge-graph (different domain) | **no 95%-style win** — both write **free**; WorkBoard SKILL.md **28.5% lighter** | lighter per-prompt (0 vs WB's 306 nudge); different shape, not a rival |

---

## Per-dimension matrix

| Dimension | vs **mem0** | vs **claude-mem** | vs **Letta** | vs **graphify** |
|---|---|---|---|---|
| **Build memory** (ingest tokens) | WB **98.7% fewer** (64K vs 5.1M) | WB **~99% fewer** (≈11K vs 5.1M) | n/a (per-turn cost) | n/a (different domain) |
| **Persist / session** (write) | WB **0** vs 1 LLM call (~5.5K tok) | WB **0** vs 1 compression call (~5.5K tok) | WB **0** vs LLM tool-calls + compaction | both **0** model tokens |
| **Live loop** (project lifetime) | WB **33.7% fewer** | WB **52.6% fewer** | WB **81.0% fewer** (92.2% trimmed) | — |
| **Per single recall** | mem0 leaner (1,800 vs **2,399**) | **WB 25.9% lighter** (2,399 vs 3,237) | Letta leaner (1,064 vs **2,399**) | graphify leaner (1,373)* |
| **Recall vs full-context** (26K) | WB **90.8% fewer** · mem0 93.1% | — | — | — |
| **Per-turn injection** | WB 306 (trim 40) · mem0 **0** | WB 306 · claude-mem grows w/ memory | WB **306** vs Letta **3,444** | WB 306 vs graphify **0** |

\* graphify's "recall" is a code-subgraph query — a different domain (code structure,
not work outcomes), so it's a different-shape comparison, not a head-to-head. See
the dedicated `graphify-comparison/` study (real `graphifyy 0.8.41` install).

> **Scenario note:** the *live-loop* % for mem0 & claude-mem is over **100 sessions ×
> 3 recalls** (their cost is per-*session*); Letta's is over **100 sessions × 50
> turns × 3 recalls** (its cost is per-*turn*). Each % is computed on that peer's own
> scenario — they are not a shared absolute base.

---

## Head-to-head by competitor

Each peer on its own axes (same tokenizer, `tiktoken cl100k`; settings favor the peer).

### WorkBoard vs mem0
| Axis | WorkBoard | mem0 | Winner |
|---|--:|--:|:--|
| Build the memory *(input tok)* | 64,162 | 5,095,769 | 🟢 **WorkBoard −98.7%** |
| Persist / session | **0 model calls** | 1 LLM extract call (~5,462 tok) + embed | 🟢 **WorkBoard (free)** |
| Live loop *(100 sessions × 3)* | 719,700 | 1,086,200 | 🟢 **WorkBoard −33.7%** |
| Per single recall | 2,399 | 1,800 | mem0 *(leaner)* |
| Recall vs full-context *(26K)* | 90.8% fewer | 93.1% fewer | ~tie *(both ≈90%)* |
| Per-turn injection | 306 *(trim 40)* | 0 | mem0 |

### WorkBoard vs claude-mem
| Axis | WorkBoard | claude-mem | Winner |
|---|--:|--:|:--|
| Build the memory *(input tok)* | ~10,546 | 5,095,769 | 🟢 **WorkBoard ~−99%** |
| Persist / session | **0 model calls** | 1 compression call *(full subscription tier)* | 🟢 **WorkBoard (free)** |
| Live loop *(100 sessions × 3)* | 719,700 | 1,517,300 | 🟢 **WorkBoard −52.6%** |
| Per single recall | 2,399 | 3,237 | 🟢 **WorkBoard −25.9%** |
| Backfill past history | mines your history | forward-only *(no bulk command)* | 🟢 **WorkBoard** |

### WorkBoard vs Letta (MemGPT)
| Axis | WorkBoard | Letta | Winner |
|---|--:|--:|:--|
| In-context memory / turn | 306 *(0 carried)* | 3,444 *(blocks + tool schemas + system prompt)* | 🟢 **WorkBoard** |
| Persist / session | **0 model calls** | LLM tool-call per write + Haiku compaction | 🟢 **WorkBoard** |
| Live loop *(100 × 50 × 3)* | 2,259,400 *(929,400 trimmed)* | 11,909,200 | 🟢 **WorkBoard −81.0% (−92.2%)** |
| Per single recall | 2,399 | 1,064 | Letta *(leaner)* |

### WorkBoard vs graphify
| Axis | WorkBoard | graphify | Winner |
|---|--:|--:|:--|
| Always-on / prompt | 306 | 61 *(cached)* | graphify |
| SKILL.md on engage | 5,898 | 8,245 *(+9,704 refs)* | 🟢 **WorkBoard −28.5%** |
| Per recall | 2,399 *(work Qs)* | 1,374 *(code Qs)* | different questions |
| Write / keep current | 0 | 0 | tie |
| Big artifact autoload | never | never | tie |

> graphify is a **code** knowledge-graph (different domain) — a complement, not a memory rival.
> *WorkBoard's build cost varies with harvest config (hourly bucket size); both figures are <1.3% of the peer's compression total — the **reduction %** is the robust number.*

---

## ⚡ Controversy — claims vs. what we actually measured

> Every figure below is from a **real run** or the vendor's **own** published numbers, on the same corpus and tokenizer, with settings that *favor the peer*. We'll correct anything demonstrably wrong — **reproduce it yourself**; each study folder ships the harness.

**1. The "90% / 95%" headlines are measured against the *dumbest possible baseline* — not a competitor.**
mem0's *"90% fewer tokens"* and claude-mem's *"~95% / ~10×"* are both vs **full-context / full-transcript reload** — i.e. pasting your *entire* history into every prompt. That isn't "more efficient than the alternatives"; it's "cheaper than the worst possible approach." Run it head-to-head and the real gaps are **34–53% on the loop**, and on *building* memory WorkBoard is **~98–99% lighter** than both.

**2. claude-mem can't actually remember your past — it only records forward from install.**
Our real, fully-sandboxed run (node 22 + Bun + uv + Chroma worker) found **no bulk / bootstrap / backfill command** anywhere in claude-mem's CLI or worker routes. It compresses *new* sessions via a live hook; to "remember" 100 past sessions you'd replay each through the summarize hook = **100 compression calls**. WorkBoard explicitly mines your history. *(`claude-mem/REAL_RUN_FINDINGS.md`)*

**3. claude-mem's "memory" runs on your full-price model tier — every session.**
That compression call goes through the Claude Agent SDK on your **main subscription tier**, *not* a cheap or detached tier. Every session silently spends full-tier compute to compress — measured in the same run, and it makes WorkBoard's *0 model calls* look even better.

**4. graphify ships no hook — despite its docs describing one.**
graphify's rendered docs describe a **PreToolUse hook that fires on every file read**. The real sandboxed install (`graphifyy 0.8.41`) writes **no `settings.json` and no hook entry** — that hook never runs. *(To graphify's credit, this makes its per-prompt cost 0 — but the advertised integration isn't what installs.)* *(`graphify-comparison/REPORT.md`)*

**The pattern:** the splashy efficiency numbers in this space are measured against naive baselines, never head-to-head — and at least one tool's docs describe an integration its installer doesn't ship. WorkBoard publishes the head-to-head, the harness, and the corpus fingerprints, so nobody has to take our word for it. **Show us where we're wrong and we'll fix the number.**

---

## How to read this (the recurring gotcha)

The two "recall" rows look contradictory but aren't:
- **Per single recall:** mem0 (1,800) and Letta (1,064) are *smaller* than WorkBoard's
  content-rich cards (2,399) — they win the **lookup**.
- **Live loop:** WorkBoard wins by 34–81% — because **building and persisting memory
  are free for WorkBoard**, and that dwarfs any single-recall difference. WorkBoard
  wins the **loop**.

"X% fewer" always means a **reduction** (a saving), same direction as mem0's marketed
"90% fewer."

---

## Why WorkBoard comes out ahead on the loop

mem0, claude-mem, and Letta all pay an **LLM tax to remember**: mem0/claude-mem run an
extraction/compression call every session; Letta re-sends its memory machinery every
turn. **WorkBoard's writes are free** — the card text is the agent's normal turn
output, committed by a deterministic CLI, and the board is never auto-loaded into
context. That structural difference is the whole story.

## What the peers do better (neutral)

- **Zero discipline:** mem0, claude-mem, and Letta capture memory **automatically**,
  across projects, with no habit required. WorkBoard needs the live-carding discipline
  and is project-scoped.
- **Leaner single lookups:** mem0 and Letta inject a smaller bundle per query.
- **Vague semantic recall:** the vector systems can surface things that were never
  explicitly recorded; WorkBoard only knows what was carded.

**Bottom line:** these are complements. The memory systems are *automatic
conversational/semantic memory*; WorkBoard is the *structured, free-to-maintain
project ledger* — cheapest to build, cheapest to keep current, and strongest on
multi-card "what shipped / what's still open" recall.

---

*Sources: `mem0-comparison/REPORT.md`, `claude-mem/REPORT.md`, `letta-comparison/REPORT.md`
(Study 1b, Letta), and `graphify-comparison/REPORT.md` (graphify, real install). Cards
#730 / #733 / #734 / #735 / #749 / #751.*
