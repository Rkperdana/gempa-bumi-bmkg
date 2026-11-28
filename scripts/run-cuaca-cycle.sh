#!/usr/bin/env bash
set -uo pipefail

collect_status=0
publish_status=0

python scripts/dataloka_wp_cuaca.py --mode collect || collect_status=$?
bash scripts/save-cuaca-state.sh || { echo "Cannot persist weather ledger; stopping this cycle" >&2; exit 1; }

if [[ "$collect_status" -eq 0 && -n "${PING_URL:-}" ]] &&
   jq -e '.unread_urls == []' data/dataloka-cuaca-state.json >/dev/null; then
  curl -fsS --max-time 10 -o /dev/null "$PING_URL" || true
fi

test -n "${WP_USERNAME:-}" || { echo "Missing DATALOKA_WP_USERNAME"; exit 1; }
test -n "${WP_APP_PASSWORD:-}" || { echo "Missing DATALOKA_WP_APP_PASSWORD"; exit 1; }

python scripts/dataloka_wp_cuaca.py --mode publish-queue || publish_status=$?
bash scripts/save-cuaca-state.sh || { echo "Cannot persist weather ledger; stopping this cycle" >&2; exit 1; }

if [[ "$collect_status" -ne 0 || "$publish_status" -ne 0 ]]; then
  echo "Weather cycle failed: collect=$collect_status publish=$publish_status" >&2
  exit 1
fi
