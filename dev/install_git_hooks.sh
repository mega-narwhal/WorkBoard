#!/usr/bin/env bash
#
# install_git_hooks.sh — install board-steward's repo git hooks.
#
# Git hooks live in .git/hooks (untracked), so they don't travel with a clone.
# This installer copies the version-controlled hooks from dev/git-hooks/ into
# place, making the setup reproducible: run it once after cloning.
#
# Currently installs:
#   post-commit  → runs the fast regression smoke (dev/smoke_test.py --fast,
#                  #316) after each commit. (#529: the old skill-dir sync step
#                  was retired with the marketplace-plugin model.)
#
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_SRC="$REPO/dev/git-hooks"
HOOKS_DST="$REPO/.git/hooks"

for hook in "$HOOKS_SRC"/*; do
  name="$(basename "$hook")"
  install -m 0755 "$hook" "$HOOKS_DST/$name"
  echo "✓ installed $name → .git/hooks/$name"
done
echo "Done. Hooks active. (post-commit runs the fast regression smoke on your next commit.)"
