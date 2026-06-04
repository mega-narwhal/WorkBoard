# skills/ — personal dev/ops skills (canonical, git-tracked)

These are **auxiliary** Claude Code skills for developing/testing board-steward —
**not** part of the distributed plugin (the plugin ships `SKILL.md` + hooks via
`.claude-plugin/`). They live here so they're under version control, and are
**symlinked** into `~/.claude/skills/` so Claude Code still discovers them and
they're invoked as `/clean-slate` and `/e2e`.

| Skill | Invoke | What it does |
|---|---|---|
| `clean-slate/` | `/clean-slate` | Full teardown for a fresh-user / first-run test (backs up, wipes state + plugin + cache). |
| `e2e/` | `/e2e` | Reusable end-to-end test harness (multi-board + reconciliation), isolated, never touches the live board. |

## The symlink setup (how to reproduce on a new machine)

```bash
ln -s "$PWD/skills/clean-slate" ~/.claude/skills/clean-slate
ln -s "$PWD/skills/e2e"         ~/.claude/skills/e2e
```

Edit the files **here** (the repo copy is canonical); the symlink means
`~/.claude/skills/<name>` always reflects them. If `~/.claude/skills/<name>`
already exists as a real dir, move it into this folder first, then symlink.
