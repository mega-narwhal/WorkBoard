#!/usr/bin/env bash
#
# sync_skill.sh — propagate this repo (source of truth) → the installed skill dir.
#
# WHY: board-steward lives in two places — the dev repo (~/Desktop/WorkBoard,
# with .git/board/training_data) and the installed skill that Claude Code
# actually loads (~/.agents/skills/board-steward, a clean standalone copy).
# They used to be kept in lockstep by a manual `cp`, which silently drifts the
# moment one file is forgotten (board #302). This script is the ONE sync path:
# an rsync mirror that drops the dev-only cruft and never touches runtime data.
#
# USAGE:
#   dev/sync_skill.sh           # mirror repo -> skill
#   dev/sync_skill.sh --check   # report drift only, change nothing (exit 1 if drift)
#
# It also runs automatically after every commit via the post-commit git hook
# (see dev/install_git_hooks.sh), so the installed skill always reflects what
# was last committed. Override the destination with BOARD_STEWARD_SKILL_DIR.
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL="${BOARD_STEWARD_SKILL_DIR:-$HOME/.agents/skills/board-steward}"

# Everything the installed skill must NOT carry:
#   .git/.gitignore/.DS_Store/__pycache__/*.pyc  — dev + VCS + OS cruft
#   board/                                        — the live dev board (skill ships templates/, not state)
#   training_data/                                — multi-hundred-MB transition corpus, dev-only
#   board-sim-*/                                  — throwaway History Replay scratch dirs
#   telemetry/                                    — RUNTIME data: the skill writes its own events.jsonl here
EXCLUDES=(
  --exclude '.git'
  --exclude '.gitignore'
  --exclude '.DS_Store'
  --exclude '__pycache__'
  --exclude '*.pyc'
  --exclude 'board'
  --exclude 'training_data'
  --exclude 'board-sim-*'
  --exclude 'telemetry'
)

if [[ "${1:-}" == "--check" ]]; then
  # Dry-run: list what WOULD change. Empty itemized output = in sync.
  out="$(rsync -ai --delete --dry-run "${EXCLUDES[@]}" "$REPO/" "$SKILL/" 2>/dev/null | grep -vE '^\.d\.\.t\.\.\.\.\.\. \./?$' || true)"
  if [[ -n "$out" ]]; then
    echo "DRIFT — repo and skill differ:"
    echo "$out"
    exit 1
  fi
  echo "✓ in sync — $REPO == $SKILL (modulo excludes)"
  exit 0
fi

mkdir -p "$SKILL"
rsync -a --delete "${EXCLUDES[@]}" "$REPO/" "$SKILL/"
echo "✓ synced  $REPO  →  $SKILL"
