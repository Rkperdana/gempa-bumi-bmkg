#!/usr/bin/env python3
"""One-time reversible cleanup of accidental Dataloka draft 9058.

The original, manually edited draft 9041 is never modified. The accidental
duplicate 9058 is only moved to WordPress Trash if its full raw body still
matches the exact SHA-256 digest confirmed in the production ledger.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.dataloka_wp_gempa import WordPress, hash_value

ORIGINAL_ID = 9041
ACCIDENTAL_ID = 9058
EVENT_MARKER = "<!-- dataloka-bmkg:cec790483c9fbd -->"
ACCIDENTAL_DIGEST = "68899c4e2c7e616c974dc0309ef5332bef8665d94f99bed65c26d42a0b23e325"


def cleanup(wp):
    target = wp.by_id(ACCIDENTAL_ID)
    if target.get("status") == "trash":
        print("Dataloka duplicate draft 9058 already in Trash; no changes")
        return
    if int(target.get("id", 0)) != ACCIDENTAL_ID:
        raise RuntimeError("Unexpected WordPress duplicate post ID")
    if target.get("status") != "draft":
        raise RuntimeError("Duplicate was modified or published; abort cleanup")
    raw = (target.get("content") or {}).get("raw")
    if not isinstance(raw, str) or EVENT_MARKER not in raw:
        raise RuntimeError("Original bot ownership marker missing; abort cleanup")
    if hash_value(raw) != ACCIDENTAL_DIGEST:
        raise RuntimeError("Duplicate was edited after creation; abort cleanup")

    original = wp.by_id(ORIGINAL_ID)
    if int(original.get("id", 0)) != ORIGINAL_ID:
        raise RuntimeError("Original editorial draft 9041 not accessible")
    # Only the automatically created and still-unmodified duplicate is touched.
    outcome = wp.call("DELETE", f"posts/{ACCIDENTAL_ID}",
                      params={"force": "false"})
    if outcome.get("status") != "trash":
        raise RuntimeError("WordPress did not confirm reversible trash status")
    print("Accidental duplicate 9058 moved to Trash. Original 9041 preserved.")


def main():
    wp = WordPress(os.getenv("WP_USERNAME"), os.getenv("WP_APP_PASSWORD"))
    cleanup(wp)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"SAFE CLEANUP NOT COMPLETED: {exc}", file=sys.stderr)
        raise
