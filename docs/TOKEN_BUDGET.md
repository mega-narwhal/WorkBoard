# Token budget — `board-steward`

Measured 2026-05-28. The skill's promise is **zero per-prompt context bleed**; this doc backs that with numbers and sets degradation thresholds.

## TL;DR

- **~222 tokens/session** baseline (SessionStart hook once, no per-prompt injection).
- **~7,666 tokens** when SKILL.md body loads (only on board engagement, not every prompt).
- **0 tokens** for board.json (~33K on disk, never auto-loaded — CLI-only access).
- **Lightest per-prompt skill of the five peers benchmarked.** Heavier on cold-engagement than CLAUDE.md, lighter on every other axis.

## Local measurements

Counted from the live WorkBoard install (rev 1156, 82 cards, 54 in Done).

| Source | Bytes | ≈ Tokens | When loaded |
|---|--:|--:|---|
| SessionStart hook output | 888 | **222** | Once per session |
| SKILL.md (full) | 30,664 | **7,666** | When skill is engaged (board work) |
| index.json | 39,693 | 9,923 | Only on explicit Read (never auto) |
| board.json | 131,560 | 32,890 | Only on explicit Read (never auto) |
| `card.py list --column X` | 216 | ~54 | Per query |
| `card.py show <num>` | ~4,730 | ~1,180 | Per card detail |
| Done-column writeups (54 cards) | 35,917 | 8,979 | Inside board.json — cold |
| All-card origin text (82) | 16,284 | 4,071 | Inside board.json — cold |
| All-card notes text (82) | 20,364 | 5,091 | Inside board.json — cold |

### Per-session cost model

```
COLD session (no board engagement):
  hook block                         222 tok
  SKILL description in skill list    ~80 tok  (set by Claude harness, not us)
                                    --------
                                     ~300 tok / session

WARM session (board engaged once, +5 card actions):
  hook block                         222 tok
  SKILL.md body (one load)          7,666 tok
  5 × card.py show                  5,900 tok
                                    --------
                                  ~13,800 tok / session
```

A typical 50-turn coding session at ~2K tokens/turn = ~100K total. Board-steward warm cost ≈ 13.8% of session budget. Cold cost ≈ 0.3%.

## Peer benchmark

| Skill | Per-prompt | Per-action | 30-day storage | Compaction | Source |
|---|--:|--:|---|---|---|
| **CLAUDE.md baseline** | full file every turn (cached) | 0 | grows unbounded | manual prune | [docs](https://code.claude.com/docs/en/memory) |
| **board-steward** (this) | **~0** | 50–1,200 (CLI stdout) | board.json grows ~1–3KB/card; cold on disk | `archive_done.py` >14d | self |
| **claude-mem** | ~thousands at SessionStart | tens-of-K to fetch full | SQLite + ChromaDB, unbounded | AI-compressed summaries | [repo](https://github.com/thedotmack/claude-mem) |
| **graphify** | ~1,500 per PreToolUse fire | ~1,500 per Grep/Glob | pre-compiled graph file | full rebuild | [repo](https://github.com/safishamsi/graphify) |
| **mem0** (MCP) | 0 | 6,719–6,956 per `search_memory` | Qdrant/Valkey vector DB | summarize-on-write | [bench](https://mem0.ai/blog/mem0-the-token-efficient-memory-algorithm) |
| **letta / MemGPT** (MCP) | ~1,000 baseline (2 core blocks × 500 tok) | tool-call cost for recall/archival | SSD + disk, unbounded | self-evicts core when full | [docs](https://docs.letta.com/guides/core-concepts/memory/memory-blocks/) |

### Where board-steward sits

**Cheapest per-turn of the set.** Closest architectural peer is **graphify** (CLI-as-tool + opt-in injection), but graphify's automatic PreToolUse fire makes its amortized cost higher across a coding session. Closest *cost* peer is the **CLAUDE.md baseline**, but board-steward avoids the "grows forever in system prompt" failure mode that bit Claude Code 2.1.96 ([#45188](https://github.com/anthropics/claude-code/issues/45188)) — its 131KB lives on disk, not in context.

## Degradation curve

Projected cost at scale (assumes current shape: ~30% Done, ~10% writeup avg 700B):

| Card count | board.json | index.json | SessionStart digest | SKILL.md |
|--:|--:|--:|--:|--:|
| 82 (today) | 131 KB | 40 KB | 222 tok | 7,666 tok |
| 250 | ~400 KB | ~120 KB | ~250 tok | static |
| 500 | ~800 KB | ~240 KB | ~260 tok | static |
| 1,000 | ~1.6 MB | ~480 KB | ~270 tok | static |

board.json and index.json grow linearly, but neither auto-loads, so this doesn't tax context — it taxes disk + the rare explicit `Read board.json` slip.

The SessionStart digest is bounded: counts + last-shipped line are fixed-shape regardless of card count.

## Hard caps + thresholds

Enforced (or to be enforced) so the skill doesn't quietly bloat:

| Surface | Cap | Enforced by |
|---|--:|---|
| SessionStart hook block | ≤ 300 tok | hand-coded; PR-time review |
| SKILL.md (always-load body) | ≤ 2,000 tok | **NOT yet — currently 7,666** (see follow-up: SKILL.md core/reference split) |
| index.json | ≤ 12,000 tok (~48 KB) | `archive_done.py --days 14` sweeps old Done |
| Done writeup median | ≤ 200 tok/card | hand-coded; reconciliation §F flags overruns |
| Single `card.py show` | ≤ 2,000 tok | natural — only bloats if writeup is unbounded |

## Token-cost line for README

> **Cost to install:** ~80 tokens of skill-list description (always-on, set by the harness). ~222 tokens once per session for the board digest. The full SKILL.md (~7.7K tokens) loads only when Claude actively engages with the board. The board itself (board.json, can be 130 KB+) lives on disk and is never auto-loaded — Claude queries it via `card.py` CLI primitives that return tens to a few thousand tokens per call.

## Open hardening work (filed as follow-ups)

- **SKILL.md core/reference split** — Trim core to ~1.5K tokens (mandatory + decision table + lifecycle §E + reconciliation §F + canonical write recipe), move playbook/schema/tags/install/bootstrap to `docs/` files loaded on demand.
- **Schedule `archive_done.py`** — Currently a manual script. Wire into a launchd timer (or serve.py background thread) so it runs daily.
- **Token-cost field in telemetry** — Add `est_tokens` to `log_event.py` schema so `report.py` can flag bloat trends over time.
- **Cap enforcement** — `card.py` warns on Done-writeup > 800B; `serve.py` warns on index.json > 50KB.
