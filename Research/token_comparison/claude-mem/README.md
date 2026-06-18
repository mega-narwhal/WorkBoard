# claude-mem-comparison

A **self-contained, reproducible** efficiency study: **WorkBoard vs claude-mem**
(with mem0 cited). Everything needed to re-derive every number lives in this one
folder — it does **not** depend on the WorkBoard product being present.

Card #730 / #736 / #737 / #739. Tokenizer: `tiktoken cl100k` (same for both sides).

---

## Start here

| Read this | For |
|---|---|
| **`REPORT_FULL.md`** | The complete, detailed write-up (all 3 studies + real run + caveats). |
| `REPORT.md` | Shorter combined report. |
| `REPORT_BOOTSTRAP.md` | Study A only, detailed. |
| `REPORT_LIVE.md` | Study C only, detailed. |
| `REPRODUCIBILITY.md` | Provenance rules: what's measured vs modeled vs cited. |
| `REAL_RUN_FINDINGS.md` | What the real sandboxed claude-mem run established. |
| **`PROCESS_LOG.md`** | **Step-by-step of everything done** — full context to resume without rerunning. |

## The headline

- **Bootstrap (build memory):** WorkBoard uses **98.6–99.2% fewer model-input
  tokens** and 5–15× fewer model calls than claude-mem on the same corpus.
- **Recall (use memory):** WorkBoard loads **25.9% fewer tokens** to answer
  (33% on lifecycle queries); wins 16/19. claude-mem wins tight pinpoints + 1
  off-board fact.
- **Live (persist work):** WorkBoard adds **0 model calls/session** (inline
  carding) vs claude-mem's 1 full-tier compression call (~5,462 tok) → **0 vs
  546,200 tokens over 100 sessions**.
- All conservative (settings favor claude-mem). Honest tradeoffs documented.

## Reproduce (one folder, no product needed)

```bash
cd ~/Desktop/claude-mem-comparison
python3 run_bootstrap.py      # Study A   -> results/raw/bootstrap.json
python3 run_recall.py         # Study B   -> results/raw/recall.json
python3 replay_session.py     # Study C   -> results/raw/live.json
python3 render_report.py      # -> REPORT.md
python3 report_bootstrap.py   # -> REPORT_BOOTSTRAP.md
python3 report_live.py        # -> REPORT_LIVE.md
python3 report_full.py        # -> REPORT_FULL.md
```
Deterministic — re-running yields identical numbers (no network, no model calls).

## What's in here

```
claude-mem-comparison/
├── README.md  PROCESS_LOG.md  REPRODUCIBILITY.md  REAL_RUN_FINDINGS.md
├── REPORT_FULL.md  REPORT.md  REPORT_BOOTSTRAP.md  REPORT_LIVE.md
├── run_claude_mem_tiny.md          # optional real claude-mem validation steps
├── tokencount.py                   # shared tokenizer (the fairness control)
├── corpus_stats.py  build_fixtures.py  queries.json
├── peers/
│   ├── workboard_adapter.py        # WorkBoard — MEASURED (real code, vendored)
│   └── claude_mem_adapter.py       # claude-mem — MODELED from its published #s
├── run_bootstrap.py run_recall.py replay_session.py
├── render_report.py report_bootstrap.py report_live.py report_full.py
├── lib/product_scripts_ro/         # read-only vendored copy of WorkBoard/scripts/*
├── board_snapshot.json             # frozen board copy (local; never the live board)
├── corpora/{tiny,medium,large}/    # frozen transcript fixtures (local)
├── reference/                      # TOKEN_BUDGET.md + COMPARISON.md snapshots (cited)
└── results/raw/                    # machine-readable outputs
```

## Safety & provenance (the short version)

- **Self-contained:** product scripts are vendored read-only under
  `lib/product_scripts_ro/`. Nothing here reads or writes the live product.
- **WorkBoard = measured** (its real code run against a frozen board copy).
- **claude-mem = modeled** from its own published per-layer numbers; a real
  sandboxed run validated the *structure* (see `REAL_RUN_FINDINGS.md`).
- `board_snapshot.json` and `corpora/` are local-only (may hold private data).

See `REPRODUCIBILITY.md` for the full per-number provenance table.
