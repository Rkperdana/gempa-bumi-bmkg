#!/usr/bin/env python3
"""One-time SEO-only update for BMKG Manggarai draft ID 9057.

Modify only Yoast focus keyphrase and meta description. Do NOT rewrite
the editor's title, article body, image, excerpt, permalink, or tags.
Refuse the change if its current SEO differs from the last bot-owned digest.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dataloka_wp_gempa import (
    WordPress, YOAST_KEYS, article, hash_value, read_state,
)

POST_ID = 9057
EVENT_KEY = "2cba3dde5800ca"
MARKER = f"<!-- dataloka-bmkg:{EVENT_KEY} -->"
EDITABLE_KEYS = ("_yoast_wpseo_focuskw", "_yoast_wpseo_metadesc")


def reconcile(wp, state):
    record = next((item for item in state["events"]
                   if item.get("key") == EVENT_KEY
                   and item.get("post_id") == POST_ID), None)
    if record is None:
        raise RuntimeError("Expected event and WordPress post 9057 are not in publisher ledger")
    event = record["data"]
    if event.get("magnitude") != 4.8 or "Ruteng" not in event.get("region", ""):
        raise RuntimeError("Unexpected earthquake event; no SEO writes permitted")

    post = wp.by_id(POST_ID)
    if int(post.get("id") or 0) != POST_ID or post.get("status") != "draft":
        raise RuntimeError("Article is not the expected WordPress draft; abort")
    raw = (post.get("content") or {}).get("raw")
    if not isinstance(raw, str) or MARKER not in raw:
        raise RuntimeError("Bot ownership marker missing; abort without editing")
    current_meta = post.get("meta")
    if not isinstance(current_meta, dict) or any(k not in current_meta for k in YOAST_KEYS):
        raise RuntimeError("Yoast REST metadata unavailable; abort")

    before = {k: str(current_meta[k]) for k in YOAST_KEYS}
    target = article(event)["yoast_meta"]
    updated = dict(before)
    for key in EDITABLE_KEYS:
        updated[key] = target[key]
    # No changes to Yoast SEO title, even if the editor customized it.
    if all(before[k] == updated[k] for k in EDITABLE_KEYS):
        print(f"Dataloka post {POST_ID}: focus and meta description already correct; no update")
        return

    stored_digest = record.get("yoast_meta_digest")
    current_digest = hash_value(json.dumps(before, sort_keys=True, ensure_ascii=False))
    if not stored_digest or stored_digest != current_digest:
        raise RuntimeError("Yoast fields have been edited since last bot write; refusing override")

    original = {
        "raw": raw,
        "slug": post.get("slug"),
        "title": (post.get("title") or {}).get("raw"),
        "featured_media": int(post.get("featured_media") or 0),
    }
    # REST partial update: only requested Yoast values, never editorial fields.
    wp.call("POST", f"posts/{POST_ID}", payload={"meta": {
        key: updated[key] for key in EDITABLE_KEYS
    }})
    confirmed = wp.by_id(POST_ID)
    wp._verified_yoast(confirmed, updated)
    after = {
        "raw": (confirmed.get("content") or {}).get("raw"),
        "slug": confirmed.get("slug"),
        "title": (confirmed.get("title") or {}).get("raw"),
        "featured_media": int(confirmed.get("featured_media") or 0),
    }
    if original != after:
        raise RuntimeError("WordPress changed an editorial field during SEO-only update")
    if confirmed.get("status") != "draft":
        raise RuntimeError("Unexpected post status after SEO-only update")
    print(f"Dataloka post {POST_ID}: focus keyphrase and meta description updated, "
          "editorial content/title/featured image/permalink preserved")
    print(f"Focus keyphrase: {updated['_yoast_wpseo_focuskw']}")
    print(f"Meta description: {updated['_yoast_wpseo_metadesc']}")


def main():
    wp = WordPress(os.getenv("WP_USERNAME"), os.getenv("WP_APP_PASSWORD"))
    reconcile(wp, read_state())


if __name__ == "__main__":
    main()
