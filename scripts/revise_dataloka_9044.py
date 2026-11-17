#!/usr/bin/env python3
"""One-time, idempotent correction of Dataloka WordPress post 9044.

Source: BMKG press release and analyzed realtime solution, 17 Nov 2026:
https://stageof-jayapura.bmkg.go.id/siaran-pers/315/
https://www.bmkg.go.id/gempabumi/gempabumi-realtime

Does not create posts or touch any other WordPress ID.
Reads credentials ONLY from Actions Secrets.
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request

POST_ID = 9044
BASE = "https://dataloka.id/wp-json/wp/v2"
BMKG_SOURCE = "https://www.bmkg.go.id/gempabumi/gempabumi-realtime"
MARKER = "bmkg-parameter-revision-2026-11-17-maluku-tenggara"
REVISION_NOTE = (
    '<p><strong>Pembaruan parameter BMKG (17 November 2026):</strong> '
    'BMKG merevisi magnitudo gempa dari M7,1 menjadi <strong>M6,8</strong> '
    'dan kedalamannya dari 115 kilometer menjadi <strong>97 kilometer</strong>. '
    'Titik episenter hasil analisis berada pada 6,12° LS dan 131,63° BT, '
    'sekitar 132 kilometer barat daya Maluku Tenggara. '
    'Gempa ini tidak berpotensi tsunami. '
    '<a href="' + BMKG_SOURCE + '">Sumber: siaran pers BMKG</a>.</p>'
    '<!-- ' + MARKER + ' -->'
)
REPLACEMENTS = (
    (r"\bM7,1\b", "M6,8"),
    (r"\bmagnitudo 7,1\b", "magnitudo 6,8"),
    (r"\bkedalaman 115 kilometer\b", "kedalaman 97 kilometer"),
    (r"\b6,03 derajat lintang selatan\b", "6,12 derajat lintang selatan"),
    (r"\b131,62 derajat bujur timur\b", "131,63 derajat bujur timur"),
    (r"\b130 kilometer di barat daya Maluku Tenggara\b",
     "132 kilometer di barat daya Maluku Tenggara"),
)


def update_terms(source):
    out = source
    for old, new in REPLACEMENTS:
        out = re.sub(old, new, out, flags=re.IGNORECASE)
    return out


def revise_html(raw):
    if MARKER in raw:
        return raw
    if "BMKG" not in raw or "Maluku Tenggara" not in raw:
        raise ValueError("Unexpected article content; refusing to modify")
    required = ("M7,1", "magnitudo 7,1", "115 kilometer")
    if not all(old in raw for old in required):
        raise ValueError("Original earthquake parameters not present; manual review required")
    out = update_terms(raw)
    # Add a prominently visible correction directly after the lead paragraph.
    # The rest of the article (MMI table, evidence and reporter credit) is retained.
    p_end = re.search(r"</p\s*>", out, re.IGNORECASE)
    if not p_end:
        raise ValueError("Unable to locate article lead paragraph")
    out = out[:p_end.end()] + "\n" + REVISION_NOTE + out[p_end.end():]
    if MARKER not in out or out.count(MARKER) != 1:
        raise AssertionError("Correction insertion failed")
    return out


def request(method, route, username, app_password, payload=None):
    auth = base64.b64encode(
        (username + ":" + app_password).encode("utf-8")).decode("ascii")
    url = BASE + "/" + route
    body = (json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None else None)
    req = urllib.request.Request(
        url, method=method, data=body,
        headers={
            "Authorization": "Basic " + auth,
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "DatalokaEditorialCorrection/1.0",
        })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as ex:
        raise RuntimeError(
            f"WordPress HTTP {ex.code} on {method} {route}") from None


def safe_post(post):
    if int(post.get("id", -1)) != POST_ID:
        raise ValueError("Incorrect WordPress post ID")
    if post.get("status") != "publish":
        raise ValueError("Target is not currently published")
    if "maluku" not in str(post.get("slug", "")).lower():
        raise ValueError("Unexpected WordPress article slug")
    raw = (post.get("content") or {}).get("raw")
    if not isinstance(raw, str) or not raw:
        raise ValueError("WordPress raw content unavailable")
    return raw


def build_payload(post):
    raw = safe_post(post)
    if MARKER in raw:
        return None
    title = html.unescape((post.get("title") or {}).get("raw", ""))
    if "M7,1" not in title or "Maluku Tenggara" not in title:
        raise ValueError("Unexpected title; refusing to change article")
    new_raw = revise_html(raw)
    new_title = update_terms(title)
    excerpt = (post.get("excerpt") or {}).get("raw", "")
    if not isinstance(excerpt, str):
        raise ValueError("WordPress excerpt missing")
    payload = {
        "title": new_title,
        "content": new_raw,
        "excerpt": update_terms(excerpt),
    }
    # Keep slug/permalink, status, category, tags, author, featured image unchanged.
    meta = post.get("meta")
    if isinstance(meta, dict):
        changes = {}
        for key in ("_yoast_wpseo_title", "_yoast_wpseo_metadesc", "_yoast_wpseo_focuskw"):
            old = meta.get(key)
            if isinstance(old, str) and old:
                new = update_terms(old)
                if new != old:
                    changes[key] = new
        if changes:
            payload["meta"] = changes
    return payload


def run():
    user = os.getenv("DATALOKA_WP_USERNAME")
    password = os.getenv("DATALOKA_WP_APP_PASSWORD")
    if not user or not password:
        raise RuntimeError("Missing Dataloka GitHub Actions Secrets")
    before = request("GET", f"posts/{POST_ID}?context=edit", user, password)
    old_slug = before.get("slug")
    payload = build_payload(before)
    if payload is None:
        print(f"ID {POST_ID}: article already has BMKG revision note, no write needed")
        return
    # Verify no intervening manual editor change after the initial GET.
    recheck = request("GET", f"posts/{POST_ID}?context=edit", user, password)
    if (recheck.get("modified_gmt") != before.get("modified_gmt") or
            (recheck.get("content") or {}).get("raw") !=
            (before.get("content") or {}).get("raw")):
        raise RuntimeError("Article was modified during update; refusing overwrite")
    request("POST", f"posts/{POST_ID}", user, password, payload=payload)
    after = request("GET", f"posts/{POST_ID}?context=edit", user, password)
    new_raw = safe_post(after)
    if (MARKER not in new_raw or after.get("slug") != old_slug or
            "M6,8" not in html.unescape((after.get("title") or {}).get("raw", ""))):
        raise RuntimeError("Post-update verification failed")
    if "meta" in payload:
        metadata = after.get("meta", {})
        if any(metadata.get(k) != v for k, v in payload["meta"].items()):
            raise RuntimeError("Post-update Yoast SEO verification failed")
    print(f"WordPress post {POST_ID} corrected to M6.8/97 km; original permalink kept.")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print("Correction did not verify:", exc, file=sys.stderr)
        sys.exit(1)
