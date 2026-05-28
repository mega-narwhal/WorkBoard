# Discovery — how the board learns from your real work

`discover2.py` is the v2 discovery layer. It walks your Claude Code history
(plus other timestamped sources) and emits **task records** that `serve.py` /
`simulate_install.sh` turn into cards.

It replaces `discover.py` (kept around as `--legacy`).

## What changed vs `discover.py`

| | discover.py | discover2.py |
|---|---|---|
| Output shape | 1 session = 1 record | 1 record per **task** (a session can yield many tasks) |
| Files filter | In-project only — sessions that edit plans/notes/sibling repos got demoted to backlog | Both `files_touched_all` (raw) and `files_touched_in_proj` (filtered); ship gate uses the unfiltered set |
| Turn counter | `SKIP_RE continue` skipped `n_user += 1` — counted ~16% of user turns | Counts every prompt, classifies trivial separately (`n_user_total` ≠ substantive count) |
| Ship signal | `SHIP_RE` matched `done` anywhere — closer like `Done. Status:` registered | Strong words (`shipped/deployed/merged/landed/verified`) match outright; weak words (`done/fixed/works/live`) require file edits in a 60s window; sentence-final `Done.` rejected |
| Sources | jsonl + optional MEMORY.md | jsonl + memory dir mtimes + plans dir mtimes + `~/Desktop/conversation_history/conversation_raw_*.md` + `git log` |

## The model

```
                ┌── jsonl events (user/assistant turns + tool uses)
                ├── memory writes (mtime)
                ├── plans writes (mtime)
                ├── conversation_raw_*.md (parsed [USER]/[CLAUDE] markers)
                └── git commits in the project repo
                                   │
                                   ▼  merge into one timeline
                          ┌────────────────────┐
                          │  10-min buckets    │  (configurable --bucket-min)
                          └────────────────────┘
                                   │
                                   ▼  Pass 1 — Heuristic A + continuation merge
                                   │  (substantive prompt seeds a task;
                                   │   short / "wait" / fast-follow merges)
                                   │
                                   ▼  Pass 2 — soft-boundary stitching
                                   │  (adjacent tasks sharing files or with
                                   │   a short bridging follow-up merge)
                                   │
                                   ▼
                          task records (JSON)
                                   │
                                   ▼  _task_to_card_args
                          card.py add — one card per task
```

### Heuristic A — task split / merge

| Decision | Rule |
|---|---|
| MERGE | `len(text) < 40` |
| MERGE | starts with `also / actually / wait / oh / btw / see / hmm / nvm / fix / revert / and / but / still` |
| MERGE | gap ≤ 90s AND no new file mentioned |
| MERGE | trivial (`yes/ok/sure/.../<...>`) |
| SPLIT | `len(text) ≥ 150` AND gap > 5min AND no continuation marker |
| Otherwise | same bucket → merge; new bucket → split |

### Pass 2 — soft boundary reconciliation

Adjacent tasks merge if they share ≥1 file path **or** the next task's first
prompt is short (`< 40` chars). This is the "never miss a point" safety net:
hard 10-min buckets catch most things, soft reconciliation catches the rest.

## Project scope filter (Bug 1 fix)

A task is kept if **any** of these is true:

- It touched a file inside the project (`files_touched_in_proj` non-empty)
- The session's `cwd` is inside, equal to, or a parent of the project
- It contained git commits from the project repo

Sessions whose only edits were in `~/Desktop/conversation_history/`,
`~/.claude/plans/`, or a sibling repo no longer get filtered out — they get
captured as work that happened, even if the files live outside the project
tree. That's the fix for the headline smoke test: session `a08aac60` from
5/27 now lands in **Done** with files visible, where `discover.py` had it as
backlog with empty `filesEdited: []`.

## Output schema

```jsonc
{
  "project": "/path/to/project",
  "windowDays": 7,
  "bucketMin": 10,
  "convoDir": "/Users/.../Desktop/conversation_history",
  "taskCount": 30,
  "tasks": [
    {
      "ts_start": "2026-05-27T00:45:12+00:00",
      "ts_end":   "2026-05-27T00:58:33+00:00",
      "duration_min": 13.4,
      "bucket_id": 2966404,
      "source_set": ["jsonl", "plans", "memory"],
      "user_prompt": "...",
      "follow_up_prompts": ["...", "..."],
      "files_touched_all":     ["/abs/path/a.md", "/abs/path/b.py"],
      "files_touched_in_proj": ["board/board.html"],
      "tool_calls": {"Edit": 3, "Write": 1, "Read": 5},
      "ship_hits_clean": ["Now mark BOARD-V2 #65 done in the live board..."],
      "bug_hits": [], "defer_hits": [],
      "memory_writes": ["feedback_*.md"],
      "plan_refs": ["sprightly-marinating-prism.md"],
      "git_commits": [{"sha": "abc1234", "subj": "..."}],
      "n_user_total": 8,
      "cwd": "/Users/malco/Desktop/QuantifyMe/HFTAgents",
      "sessionId": "a08aac60"
    }
  ]
}
```

## Install-time ask flow

Default: silent — discover2 scans the known-safe locations (your Claude
projects dir, your memory dir, the default conversation history dir at
`~/Desktop/conversation_history/`).

If `--ask-convo` is passed AND no `conversation_raw_*.md` is found AND stdin
is a TTY, it prompts:

> Where do you keep your conversation history? (empty = skip)

The answer is saved to `<project>/board/discover.config.json` and never
re-prompted. Saved as `{"convo_dir": "/path/..."}`.

## CLI

```bash
discover2.py                                # cwd, last 7 days
discover2.py --project ~/some/repo --days 30
discover2.py --bucket-min 15 --max-tasks 50
discover2.py --debug                         # log event counts to stderr
discover2.py --legacy                        # exec discover.py instead
discover2.py --all-projects                  # don't filter by project scope
```

Same flags surface on `simulate_install.sh` as `--legacy-discover` and on
`serve.py` as `--legacy-discover`.

## Known follow-ups

- `git_commits` currently runs on the project repo only — multi-repo
  projects need a list of paths to walk.
- Noun-cluster matching for Pass 2 is intentionally NOT implemented. The
  current implementation merges only on file overlap or short bridge. Adding
  lexical noun overlap could merge more aggressively but risks over-merging.
- Memory/plan writes attach to whichever task happens to bound their ts.
  An auto-commit or mid-session memory dump that doesn't belong to a
  prompted task will land arbitrarily.
