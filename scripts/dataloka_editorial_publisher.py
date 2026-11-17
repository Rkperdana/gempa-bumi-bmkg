#!/usr/bin/env python3
"""Publication-only queue from a dedicated GitHub branch to Dataloka WordPress.

This repository is PUBLIC. NEVER put confidential/unpublished draft material
in this queue. Only add articles expressly approved for PUBLICATION.
The destination is hard-coded: https://dataloka.id; no other CMS is touched.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WP_BASE = "https://dataloka.id/wp-json/wp/v2"
SITE = "dataloka.id"
OUTBOX = re.compile(r"^publisher/outbox/[a-z0-9][a-z0-9-]{5,90}\.json$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQ_ID = re.compile(r"^[a-z0-9][a-z0-9-]{5,90}$")
YOAST = ("_yoast_wpseo_focuskw", "_yoast_wpseo_title", "_yoast_wpseo_metadesc")
ALLOWED = {
    "request_id", "site", "operation", "title", "slug", "summary",
    "content_html", "category_slug", "tags", "seo", "featured_media_id",
}
MARKER_PREFIX = "dataloka-editorial"


def required_string(data, key, maximum, minimum=1):
    v = data.get(key)
    if not isinstance(v, str) or not (minimum <= len(v.strip()) <= maximum):
        raise ValueError(f"{key} must be {minimum}-{maximum} characters")
    return v.strip()


def validate_request(doc, filename):
    if not isinstance(doc, dict):
        raise ValueError("Request must be a JSON object")
    extra = set(doc) - ALLOWED
    if extra:
        raise ValueError("Unknown request fields: " + ", ".join(sorted(extra)))
    name = Path(filename).stem
    request_id = required_string(doc, "request_id", 91, 6)
    if not REQ_ID.fullmatch(request_id) or name != request_id:
        raise ValueError("request_id must match the safe JSON filename")
    if doc.get("site") != SITE:
        raise ValueError("This publisher only supports dataloka.id")
    if doc.get("operation") != "publish":
        raise ValueError("Public GitHub repo accepts publish requests only")
    title = required_string(doc, "title", 180, 8)
    slug = required_string(doc, "slug", 180, 8)
    if not SLUG.fullmatch(slug):
        raise ValueError("Slug must be lowercase ASCII words joined by hyphens")
    summary = required_string(doc, "summary", 300, 30)
    body = required_string(doc, "content_html", 200_000, 100)
    category = doc.get("category_slug", "berita")
    if not isinstance(category, str) or not SLUG.fullmatch(category):
        raise ValueError("Invalid category slug")
    tags = doc.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 8 or any(
        not isinstance(tag, str) or not (1 <= len(tag.strip()) <= 35)
        for tag in tags
    ):
        raise ValueError("tags must contain at most eight short strings")
    if len(set(t.casefold().strip() for t in tags)) != len(tags):
        raise ValueError("Duplicate tag names")
    seo = doc.get("seo")
    if not isinstance(seo, dict) or set(seo) != {
        "focus_keyphrase", "seo_title", "meta_description"
    }:
        raise ValueError("SEO must include focus_keyphrase, seo_title, meta_description")
    focus = required_string(seo, "focus_keyphrase", 100, 3)
    seo_title = required_string(seo, "seo_title", 180, 8)
    meta_desc = required_string(seo, "meta_description", 160, 30)
    media = doc.get("featured_media_id")
    if media is not None and (type(media) is not int or media < 1):
        raise ValueError("featured_media_id must be a positive WordPress media ID")
    # The marker makes a retry idempotent without a Git writeback.
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    marker = f"<!-- {MARKER_PREFIX}:{request_id}:{digest} -->"
    if MARKER_PREFIX in body:
        raise ValueError("Reserved internal marker found in article body")
    result = {
        "request_id": request_id, "title": title, "slug": slug,
        "summary": summary, "content": body + "\n" + marker,
        "marker": marker, "category_slug": category, "tags": [t.strip() for t in tags],
        "meta": {
            "_yoast_wpseo_focuskw": focus,
            "_yoast_wpseo_title": seo_title,
            "_yoast_wpseo_metadesc": meta_desc,
        },
        "featured_media_id": media,
    }
    return result


class WPClient:
    def __init__(self, username, password):
        if not username or not password:
            raise ValueError("Missing DATALOKA_WP_USERNAME or DATALOKA_WP_APP_PASSWORD")
        self.auth = "Basic " + base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")

    def call(self, method, route, params=None, payload=None):
        url = WP_BASE + "/" + route
        if params:
            url += "?" + urllib.parse.urlencode(params)
        body = None if payload is None else json.dumps(
            payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method=method, headers={
            "Authorization": self.auth,
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "DatalokaEditorialPublisher/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=35) as r:
                return json.loads(r.read(2_000_000).decode("utf-8"))
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"WordPress HTTP {err.code} for {method} {route}") from None

    def find_slug(self, slug):
        matches = self.call("GET", "posts", {
            "slug": slug, "status": "any", "context": "edit", "per_page": 5
        })
        if not isinstance(matches, list):
            raise ValueError("Unexpected WordPress list response")
        return matches

    def get_post(self, post_id):
        return self.call("GET", f"posts/{int(post_id)}", {"context": "edit"})

    def category_id(self, slug):
        found = self.call("GET", "categories", {"slug": slug, "per_page": 10})
        exact = [x for x in found if x.get("slug") == slug]
        if len(exact) != 1:
            raise RuntimeError(f"WordPress category '{slug}' not found uniquely")
        return int(exact[0]["id"])

    def resolve_tags(self, names):
        result = []
        for name in names:
            found = self.call("GET", "tags", {"search": name, "per_page": 50})
            exact = [t for t in found if t.get("name", "").casefold() == name.casefold()]
            if exact:
                result.append(int(exact[0]["id"]))
            else:
                # No term creation: this WordPress user may not manage taxonomies.
                print(f"Tag not present in WordPress, omitted: {name}")
        return result


def verify_draft(post, req):
    if post.get("slug") != req["slug"]:
        raise RuntimeError("WordPress changed the slug; refusing to publish")
    if post.get("status") not in ("draft", "publish"):
        raise RuntimeError("WordPress returned unexpected post status")
    raw = (post.get("content") or {}).get("raw", "")
    if not isinstance(raw, str) or req["marker"] not in raw:
        raise RuntimeError("Cannot verify Dataloka editorial ownership marker")
    if raw != req["content"]:
        raise RuntimeError("Article was modified in WordPress; refusing overwrite")
    meta = post.get("meta")
    if not isinstance(meta, dict) or any(meta.get(k) != req["meta"][k] for k in YOAST):
        raise RuntimeError("Yoast fields not readable/persisted: article remains draft")
    return True


def publish_one(wp, req):
    existing = wp.find_slug(req["slug"])
    if len(existing) > 1:
        raise RuntimeError("Multiple WordPress posts share slug; manual review")
    if existing:
        post = wp.get_post(existing[0]["id"])
        # Never assume an existing post with same slug belongs to the bot.
        verify_draft(post, req)
        if post.get("status") == "publish":
            print(f"Already published: ID {post['id']} / {req['slug']}")
            return int(post["id"])
        print(f"Resume incomplete publication: ID {post['id']}")
    else:
        tags = wp.resolve_tags(req["tags"])
        payload = {
            "title": req["title"],
            "slug": req["slug"],
            "excerpt": req["summary"],
            "content": req["content"],
            "status": "draft",
            "categories": [wp.category_id(req["category_slug"])],
            "tags": tags,
            "meta": req["meta"],
            "comment_status": "closed",
        }
        if req["featured_media_id"]:
            payload["featured_media"] = req["featured_media_id"]
        created = wp.call("POST", "posts", payload=payload)
        post = wp.get_post(created["id"])
        verify_draft(post, req)
    # Check right before publish so the draft cannot be silently changed.
    current = wp.get_post(post["id"])
    verify_draft(current, req)
    if current.get("status") == "publish":
        print(f"Already published: ID {current['id']}")
        return int(current["id"])
    wp.call("POST", f"posts/{int(current['id'])}", payload={"status": "publish"})
    confirmed = wp.get_post(current["id"])
    verify_draft(confirmed, req)
    if confirmed.get("status") != "publish":
        raise RuntimeError("WordPress did not confirm publish status")
    print(f"PUBLISHED Dataloka post ID {confirmed['id']} / {req['slug']}")
    return int(confirmed["id"])


def newly_added(before, after):
    if not re.fullmatch(r"[0-9a-f]{40}", before or ""):
        raise ValueError("Bad GitHub before SHA")
    if not re.fullmatch(r"[0-9a-f]{40}", after or ""):
        raise ValueError("Bad GitHub after SHA")
    if before == "0" * 40:
        print("First branch push; no article requests processed")
        return []
    diff = subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=A", "-z",
         before, after, "--", "publisher/outbox/"], cwd=ROOT
    )
    result = []
    for name in diff.decode("utf-8").split("\0"):
        if not name:
            continue
        if not OUTBOX.fullmatch(name):
            raise ValueError(f"Unsafe article request path: {name!r}")
        result.append(name)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--health-check", action="store_true")
    parser.add_argument("--before")
    parser.add_argument("--after")
    args = parser.parse_args()
    if args.health_check:
        wp = WPClient(os.getenv("DATALOKA_WP_USERNAME"),
                      os.getenv("DATALOKA_WP_APP_PASSWORD"))
        posts = wp.call("GET", "posts", {
            "per_page": 1, "status": "any", "context": "edit"
        })
        if not isinstance(posts, list):
            raise RuntimeError("Unexpected WordPress posts response")
        wp.category_id("berita")
        print("Dataloka WordPress REST authentication and Berita category OK (read-only)")
        return
    if not args.before or not args.after:
        parser.error("--before and --after required unless --health-check")
    paths = newly_added(args.before, args.after)
    if not paths:
        print("No new editorial publication requests")
        return
    # Validate *all* requests before doing the first external write.
    requests = []
    for rel in paths:
        file = ROOT / rel
        req = validate_request(
            json.loads(file.read_text(encoding="utf-8")), rel)
        requests.append(req)
    wp = WPClient(os.getenv("DATALOKA_WP_USERNAME"),
                  os.getenv("DATALOKA_WP_APP_PASSWORD"))
    failures = []
    for req in requests:
        try:
            publish_one(wp, req)
        except Exception as exc:
            failures.append(req["request_id"])
            print(f"FAILED {req['request_id']}: {exc}", file=sys.stderr)
    if failures:
        raise RuntimeError(f"Failed {len(failures)} publication requests: {', '.join(failures)}")


if __name__ == "__main__":
    main()
