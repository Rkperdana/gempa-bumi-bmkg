#!/usr/bin/env bash
set -uo pipefail

cycles="${1:-34}"
interval="${2:-600}"
last_status=0

for ((cycle=1; cycle<=cycles; cycle++)); do
  started_at="$(date +%s)"
  echo "Starting Dataloka weather cycle $cycle/$cycles"
  if bash scripts/run-cuaca-cycle.sh; then
    last_status=0
  else
    last_status=$?
    echo "Cycle $cycle failed with status $last_status; the next cycle will retry" >&2
  fi
  if [[ "$cycle" -lt "$cycles" ]]; then
    elapsed=$(( $(date +%s) - started_at ))
    remaining=$(( interval - elapsed ))
    if [[ "$remaining" -gt 0 ]]; then
      sleep "$remaining"
    fi
  fi
done

exit "$last_status"
