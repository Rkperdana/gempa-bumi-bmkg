#!/usr/bin/env python3
"""BMKG CAP severe-weather nowcast -> Pirsadata CMS.

Separate from the Dataloka WordPress publisher and Pirsadata earthquakes/gold.
Only documented BMKG CAP XML is read. Live publishing is intentionally gated
until a dedicated Pirsadata weather CMS endpoint implements the contract.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from dataloka_wp_cuaca import (
    UTC, ROOT, active, date_label, fetch_rss, fetch_xml, fingerprint, instant,
    parse_cap, parse_rss, slugify, time_label,
)
from pirsadata_cuaca_image import render

STATE = ROOT / "data" / "pirsadata-cuaca-state.json"
SITE_HOST = "pirsadata.perdanark.chatgpt.site"
POLICY = "pirsadata-nowcast-v1"  # Contract to implement in the Pirsadata CMS.
EDITORIAL_VERSION = 1
MAX_ALERTS_PER_RUN = 1
MAX_NEW_ALERT_AGE_MINUTES = 90
MAX_BODY_BYTES = 1_000_000


def site_url(url, *, integration=False):
    parsed = urllib.parse.urlsplit(str(url))
    if (parsed.scheme != "https" or parsed.hostname != SITE_HOST or
            parsed.port is not None or parsed.username is not None or
            parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError("Pirsadata URL must use the canonical HTTPS site only")
    if integration:
        # NEVER send weather data to the existing earthquake endpoint.
        if (not re.fullmatch(r"/api/integrations/bmkg/[a-z0-9-]+", parsed.path)
                or parsed.path.endswith(("/earthquakes", "/ingest"))):
            raise ValueError("A dedicated Pirsadata BMKG weather endpoint is required")
    elif not re.fullmatch(r"/(?:tag|topik)/[a-z0-9-]+/?", parsed.path):
        raise ValueError("Pirsadata topic link must be an actual topic/tag route")
    return url


def article(entry, topic_url=None):
    """Five editorial paragraphs, then a separate sixth source-credit paragraph."""
    region = entry["region"]
    event = entry["event"]
    date = date_label(entry["effective"])
    issued = time_label(entry["issued"])
    effective = time_label(entry["effective"])
    expires = time_label(entry["expires"])
    clean_region = html.escape(region, quote=True)
    clean_event = html.escape(event, quote=True)
    description = html.escape(entry["description"], quote=True)
    source = html.escape(entry["url"], quote=True)
    cuaca = "cuaca"
    if topic_url:
        topic = html.escape(site_url(topic_url), quote=True)
        cuaca = f'<a href="{topic}">cuaca</a>'
    title = f"BMKG: Peringatan {event} di {region}"
    if len(title) > 125:
        title = f"BMKG Keluarkan Peringatan Dini Cuaca untuk {region}"
    summary = (
        f"BMKG menerbitkan peringatan dini {event} di {region} pada {date}. "
        f"Berlaku pukul {effective}–{expires}. Simak wilayah terdampak."
    )
    if len(summary) > 280:
        summary = (
            f"Peringatan dini cuaca BMKG di {region} pada {date}, berlaku "
            f"hingga {expires}. Pantau informasi resminya."
        )[:280]
    when = instant(entry["issued"])
    slug = (
        f"peringatan-dini-cuaca-{slugify(region)[:45].rstrip('-')}-"
        f"{when:%Y-%m-%d}-{entry['key'][:8]}"
    )
    content = (
        f'<p><strong>Pirsadata</strong> — Badan Meteorologi, Klimatologi, '
        f'dan Geofisika (BMKG) mengeluarkan peringatan dini {cuaca} '
        f'terkait {clean_event} untuk wilayah {clean_region} pada {date}.</p>'
        f'<p>Peringatan diterbitkan pukul {issued} dan berlaku mulai pukul '
        f'{effective} hingga {expires}, berdasarkan informasi resmi BMKG.</p>'
        f'<p>Wilayah yang tercakup dalam peringatan ini meliputi '
        f'{clean_region}. Rincian kondisi dan wilayah mengikuti keterangan '
        f'yang diterbitkan BMKG.</p>'
        f'<p>{description}</p>'
        f'<p>Peringatan ini memiliki masa berlaku terbatas dan dapat '
        f'diperbarui atau dicabut. Periksa <a href="{source}">'
        f'peringatan resmi BMKG</a> untuk informasi terbaru.</p>'
        f'\n<p><strong>Sumber:</strong> '
        f'<a href="{source}">Badan Meteorologi, Klimatologi, dan '
        f'Geofisika (BMKG)</a>.</p>'
    )
    return {
        "alertId": entry["key"],
        "capIdentifier": entry["identifier"],
        "issuedAt": entry["issued"],
        "effectiveAt": entry["effective"],
        "expiresAt": entry["expires"],
        "title": title,
        "slug": slug,
        "summary": summary,
        "contentHtml": content,
        "category": "Lingkungan",
        "tags": ["Featured", "BMKG", "Cuaca", "Peringatan"],
        "seoTitle": f"Peringatan Dini Cuaca {region} {date} - BMKG"[:100],
        "metaDescription": summary,
        "focusKeyphrase": f"peringatan dini cuaca {region}",
        "source": {"name": "BMKG", "url": entry["url"]},
        "sourceUrl": entry["url"],
        "editorialVersion": EDITORIAL_VERSION,
    }


def build_item(entry, topic_url=None):
    """CMS must store and verify image before returning publish success."""
    item = article(entry, topic_url=topic_url)
    jpg = render(entry)
    item["featuredImage"] = {
        "filename": f"pirsadata-cuaca-{entry['key']}.jpg",
        "mimeType": "image/jpeg",
        "width": 1200,
        "height": 675,
        "alt": f"Ilustrasi peringatan dini {entry['event']} di {entry['region']}. Sumber informasi: BMKG",
        "dataBase64": base64.b64encode(jpg).decode("ascii"),
    }
    item["fingerprint"] = fingerprint(entry)
    return item


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(item, *, endpoint, token, sites_token, opener=None):
    """One non-retryable POST. Stable idempotency key is enforced by CMS.

    Expected receipt is a new route contract, not asserted to already exist.
    """
    site_url(endpoint, integration=True)
    if not token or not sites_token:
        raise ValueError("PIRSADATA_NOWCAST_TOKEN and LENSADATA_SITES_TOKEN are required")
    raw = json.dumps({"alert": item}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError("Pirsadata CAP payload exceeds 1 MB")
    revision = hashlib.sha256(
        f"{item['alertId']}:{item['fingerprint']}:{EDITORIAL_VERSION}".encode()
    ).hexdigest()
    req = urllib.request.Request(endpoint, data=raw, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "OAI-Sites-Authorization": f"Bearer {sites_token}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "User-Agent": "Pirsadata-BMKG-Nowcast/1.0",
        "X-Pirsadata-Idempotency-Key": revision,
    })
    opener = opener or urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(req, timeout=45) as response:
            if response.headers.get_content_type() != "application/json":
                raise RuntimeError("Pirsadata CMS did not return JSON")
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Pirsadata weather endpoint returned HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        # Never blindly retry a POST, because the CMS may have committed it.
        raise RuntimeError(f"Pirsadata weather request outcome uncertain: {type(error).__name__}") from None
    if result.get("policy", {}).get("version") != POLICY or result.get("ok") is not True:
        raise RuntimeError("Pirsadata weather CMS contract is absent or unexpected")
    receipt = result.get("result") or {}
    if (receipt.get("alertId") != item["alertId"] or
            receipt.get("status") != "publish" or
            not isinstance(receipt.get("postId"), int) or receipt["postId"] <= 0 or
            not isinstance(receipt.get("featuredImageId"), int) or
            receipt["featuredImageId"] <= 0 or
            "Featured" not in (receipt.get("tags") or [])):
        raise RuntimeError("Pirsadata CMS did not verify published article, cover and Featured tag")
    return receipt


def load_state():
    if not STATE.exists():
        return {"version": 1, "alerts": {}}
    obj = json.loads(STATE.read_text(encoding="utf-8"))
    if obj.get("version") != 1 or not isinstance(obj.get("alerts"), dict):
        raise ValueError("Invalid Pirsadata weather ledger")
    return obj


def process(entries, mode, *, now=None, state=None, topic_url=None,
            publisher=None):
    if mode not in ("fixture", "dry-run", "live"):
        raise ValueError("Unsupported Pirsadata weather mode")
    now = now or dt.datetime.now(UTC)
    injected_state = state is not None
    state = state if state is not None else load_state()
    suitable = sorted((x for x in entries if active(x, now)),
                      key=lambda x: instant(x["issued"]), reverse=True)
    changed = 0
    for entry in suitable:
        old = state["alerts"].get(entry["key"], {})
        if (old.get("fingerprint") == fingerprint(entry) and
                old.get("editorialVersion") == EDITORIAL_VERSION):
            continue
        age = (now - instant(entry["issued"]).astimezone(UTC)).total_seconds() / 60
        if not old.get("postId") and age > MAX_NEW_ALERT_AGE_MINUTES:
            continue
        item = build_item(entry, topic_url=topic_url)
        print(f"{mode}: {item['title']} | {entry['url']}", flush=True)
        if mode == "live":
            if publisher is None:
                raise ValueError("Publisher must be configured in live mode")
            receipt = publisher(item)
            state["alerts"][entry["key"]] = {
                "postId": receipt["postId"],
                "featuredImageId": receipt["featuredImageId"],
                "status": receipt["status"],
                "fingerprint": item["fingerprint"],
                "editorialVersion": EDITORIAL_VERSION,
                "expires": entry["expires"],
            }
        changed += 1
        if changed >= MAX_ALERTS_PER_RUN:
            break
    if mode == "live" and not injected_state:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("fixture", "dry-run", "live"), default="fixture")
    args = parser.parse_args()
    if args.mode == "fixture":
        sample = ROOT / "tests" / "fixtures" / "nowcast-sample.xml"
        entry = parse_cap(sample.read_bytes(),
                          "https://www.bmkg.go.id/alerts/nowcast/id/CJB20251013001_alert.xml")
        item = build_item(entry)
        print(f"Fixture valid, {len(item['contentHtml'])} characters; "
              f"featured image {len(base64.b64decode(item['featuredImage']['dataBase64']))} bytes")
        return
    endpoint = os.environ.get("PIRSADATA_NOWCAST_ENDPOINT")
    token = os.environ.get("PIRSADATA_NOWCAST_TOKEN")
    sites_token = os.environ.get("LENSADATA_SITES_TOKEN")
    topic_url = os.environ.get("PIRSADATA_NOWCAST_TOPIC_URL") or None
    if topic_url:
        site_url(topic_url)
    if args.mode == "live":
        if os.environ.get("PIRSADATA_NOWCAST_ENABLED") != "true":
            raise RuntimeError("Pirsadata weather publication is not enabled")
        if not endpoint:
            raise RuntimeError("Dedicated PIRSADATA_NOWCAST_ENDPOINT not configured")
        site_url(endpoint, integration=True)
        if not token or not sites_token:
            raise RuntimeError("Pirsadata nowcast integration tokens are missing")
    rss = parse_rss(fetch_rss())
    entries = []
    for candidate in rss[:45]:
        try:
            entries.append(parse_cap(fetch_xml(candidate["url"]), candidate["url"]))
        except (ValueError, OSError, RuntimeError) as error:
            print(f"WARNING: invalid BMKG CAP ignored: {error}", file=sys.stderr)
    if rss and not entries:
        raise RuntimeError("BMKG feed has no valid CAP warnings")
    publisher = (lambda item: send(item, endpoint=endpoint, token=token,
                                   sites_token=sites_token)) if args.mode == "live" else None
    changed = process(entries, args.mode, topic_url=topic_url, publisher=publisher)
    print(f"Pirsadata weather: {changed} alerts processed in {args.mode} mode")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, urllib.error.URLError, OSError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
