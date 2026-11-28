#!/usr/bin/env bash
set -uo pipefail

cycles="${1:-1}"
interval="${2:-600}"
mode="${MODE:-dry-run}"
task="${TASK:-events}"
last_status=0
pending_state=0

persist_state() {
  git config user.name "github-actions[bot]" &&
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com" &&
  git add data/dataloka-wp-state.json || return 1
  if ! git diff --cached --quiet; then
    git commit -m "data: sinkronkan ledger publikasi gempa Dataloka" || return 1
  fi
  for attempt in 1 2 3; do
    if git fetch origin main && git rebase origin/main && git push origin HEAD:main; then
      return 0
    fi
    git rebase --abort || true
    sleep "$attempt"
  done
  echo "::error::Could not persist earthquake ledger; skip publication until recovered"
  return 1
}

for ((cycle=1; cycle<=cycles; cycle++)); do
  started_at="$(date +%s)"
  echo "Starting Dataloka earthquake cycle $cycle/$cycles"
  current_task="$task"
  if [[ "$task" == auto ]]; then
    current_task=events
    # Once the previous WIB day has ended, allow the idempotent daily draft.
    local_hm="$(TZ=Asia/Jakarta date +%H%M)"
    if ((10#$local_hm >= 45)); then current_task=daily; fi
  fi
  if [[ "$pending_state" == 1 ]]; then
    if persist_state; then pending_state=0; fi
  fi
  if [[ "$pending_state" == 0 ]]; then
    last_status=0
    python scripts/dataloka_wp_gempa.py --mode "$mode" --task "$current_task" || last_status=$?
    if [[ "$mode" == live ]]; then
      if ! persist_state; then pending_state=1; last_status=1; fi
    fi
  else
    last_status=1
  fi
  if [[ "$last_status" != 0 ]]; then
    echo "::warning::Earthquake cycle $cycle failed; the following cycle will retry"
  fi
  if ((cycle < cycles)); then
    elapsed=$(( $(date +%s) - started_at ))
    remaining=$(( interval - elapsed ))
    if ((remaining > 0)); then sleep "$remaining"; fi
  fi
done
exit "$last_status"
