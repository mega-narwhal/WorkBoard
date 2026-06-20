# Unit suite

Hermetic, fast unit tests for WorkBoard's **pure logic** and **security
invariants**. They never touch the live board, the server on `127.0.0.1:7891`,
the real port registry, the network, or an LLM — every test isolates its state
with `tmp_path` / `monkeypatch` (the same cardinal rule as
[`skills/e2e/e2e_workboard.py`](../skills/e2e/e2e_workboard.py)). The whole suite
runs in well under a second.

This complements, not replaces, the end-to-end harness: e2e covers the wired
integration paths (server POST flows, hooks, Haiku); this suite pins the
deterministic functions that integration tests can't cheaply nail down.

## Run

```bash
./tests/run.sh            # auto-detects pytest, or falls back to `uv run`
./tests/run.sh -v         # verbose
./tests/run.sh -k csrf    # one area
```

The runner needs **Python ≥3.10** (the targets use `X | None` annotations
evaluated at definition time). If `pytest` isn't installed it uses
[`uv`](https://docs.astral.sh/uv/) to fetch an ephemeral 3.12 + pytest.

CI runs the same suite on every push/PR — see
[`.github/workflows/tests.yml`](../.github/workflows/tests.yml) (matrix: 3.11, 3.12).

## What's covered

| File | Target | Why it's here |
|------|--------|---------------|
| `test_csrf_guard.py` | `serve.BoardHandler._csrf_ok` | **security** — same-origin / loopback-Host guard; allows CLI + board page, blocks CSRF, DNS-rebind, port-mismatch |
| `test_archive_path_safety.py` | `serve.BoardHandler._handle_archive` | **security** — `/archive/` containment; one `xfail` documents the known sibling-dir prefix bypass |
| `test_diff_states.py` | `serve.diff_states` | SSE event diffing — add/remove/move/edit, no-op, column changes |
| `test_rev_cas.py` | `serve._disk_rev`, `card_state._current_rev` / `_assert_base_rev` | rev compare-and-swap (lost-update protection) |
| `test_tag_taxonomy.py` | `card_state._check_tags`, `_detect_urgency` | taxonomy filtering rules + urgency detection |
| `test_need_detect.py` | `need_detect.looks_multi_need`, `count_needs` | brittle regex heuristics for multi-request prompts |
| `test_digest.py` | `hourly_common.build_digest`, `parse_card_array` | LLM-input building (400-char truncation, prose-drop) + card-array salvage |
| `test_port_registry.py` | `port_registry.assign` / `lookup` / `assignments` | sticky per-board port assignment, isolated to `tmp_path` |

Each assertion was grounded by **running the real function** and encoding its
actual output — not guessed. The one `xfail` in `test_archive_path_safety.py`
marks a real audit finding (the `startswith` containment bypass) so the suite
stays green while documenting the vuln; drop the `xfail` once the guard is fixed
and the test will enforce the fix.

## Optional: run on every push (local git hook)

Not installed automatically (a git hook auto-executes on push). To opt in:

```bash
cat > .git/hooks/pre-push <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[ "${WORKBOARD_SKIP_TESTS:-}" = "1" ] && exit 0
"$(git rev-parse --show-toplevel)/tests/run.sh" -q
EOF
chmod +x .git/hooks/pre-push
```

Bypass a one-off push with `WORKBOARD_SKIP_TESTS=1 git push`; remove the hook
with `rm .git/hooks/pre-push`.
