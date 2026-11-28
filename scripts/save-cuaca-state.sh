#!/usr/bin/env bash
set -euo pipefail
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
if [ ! -f data/dataloka-cuaca-state.json ]; then
  echo "No weather ledger written; nothing to persist"
  exit 0
fi
git add data/dataloka-cuaca-state.json
if git diff --cached --quiet; then
  echo "No weather ledger changes"
  exit 0
fi
git commit -m "data: update isolated Dataloka weather ledger"
for attempt in 1 2 3; do
  git fetch origin main
  if git rebase origin/main && git push origin HEAD:main; then
    exit 0
  fi
  git rebase --abort || true
  sleep "$attempt"
done
echo "Cannot persist ledger; WordPress slug lookup prevents duplicate posts"
exit 1
