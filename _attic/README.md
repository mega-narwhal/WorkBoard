# _attic — quarantined / superseded files

Files here are **kept for reference, not active**. Don't wire them into the
skill, the installer flow, or a demo without re-reading this note first.

---

## `install.sh` — the **wrong demo** (quarantined 2026-05-29)

`install.sh` is a one-command installer that bootstraps a board via
`serve.py --bootstrap` — which streams cards in with plain `card.py add`, so
they **plop straight into their final column**. It does **NOT** fly cards
task→IP→done.

It caused a demo mix-up on 2026-05-29: I used it to "simulate the new-user
experience," but the user had specifically built (5/28) a demo that **flies**
each card through its lifecycle. The plop-in behaviour is exactly what the user
rejected on 5/28 ("it just appears as 'done'… it needs to FLY there").

### ✅ The CANONICAL demo is `scripts/simulate_install.sh` — NOT this file.

That's the path-driven, card-flies-through-its-lifecycle harness (`#206`
SIM-HARNESS + `#207` BOARD-FLY). Two fly modes:

| Mode | Command | Compute |
|---|---|---|
| **Hourly-LLM fly** (the chosen demo architecture) | `simulate_install.sh --replay-mode hourly --chunk-size 2 --hourly-show-lifecycle` | one Haiku call per bucket — **heavy** |
| Bulk-discover fly (no LLM) | `simulate_install.sh` (default) | ~zero |

**Chosen demo architecture (2026-05-29):** the **hourly-LLM fly with
`--chunk-size 2`** (the `#217`/`#218` config from 5/28). Used as the demo
architecture *for now*.

**⚠️ Known future work:** the hourly-LLM fly is compute-heavy (a Haiku call per
bucket). The user wants it **reworked to be compute-light later** — see memory
`project_keep_webapp_lightweight` and board card. Use as-is for demos now; make
it light before any real distribution.

### Is `install.sh` dead?
Not necessarily — a real release still wants a "one command to install." When we
get there, the fix is to make the installer's demo path call
`simulate_install.sh`'s fly flow (or at least offer it) instead of the plain
bootstrap. Until then it lives here so it can't be mistaken for the demo tool.
Original: committed `c17ae8c`, board card `#263 BOARD-INSTALLER`.
