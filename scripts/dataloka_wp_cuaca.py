#!/usr/bin/env python3
"""BMKG CAP nowcasting -> Dataloka live WordPress publisher, isolated from earthquake automation.

Live mode publishes only validated active CAP alerts with Featured tag, cover and
verified Yoast meta. Requires BMKG authorization and WordPress credentials.
The default --mode fixture never accesses external services.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from dataloka_wp_gempa import EditorialConflict, WordPress, hash_value, slugify

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "dataloka-cuaca-state.json"
RSS_URL = "https://www.bmkg.go.id/alerts/nowcast/id"
RSS_FALLBACK_URL = "https://www.bmkg.go.id/alerts/nowcast/id/rss.xml"
CAP_NS = "{urn:oasis:names:tc:emergency:cap:1.2}"
UTC = dt.timezone.utc
MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni",
          "Juli", "Agustus", "September", "Oktober", "November", "Desember")
MARKER = "dataloka-nowcast:"
EDITORIAL_VERSION = 2  # 5 article paragraphs + separate source credit + contextual Cuaca link
MAX_ALERTS_PER_RUN = 1
MAX_NEW_ALERT_AGE_MINUTES = 90
MAX_BYTES = 600_000


def require_official_url(value):
    parsed = urllib.parse.urlsplit(str(value))
    if (parsed.scheme != "https" or parsed.netloc != "www.bmkg.go.id"
            or not re.fullmatch(r"/alerts/nowcast/id/[A-Za-z0-9_-]+_alert\.xml",
                                parsed.path)
            or parsed.query or parsed.fragment or parsed.username):
        raise ValueError("RSS contained non-official CAP URL")
    return value


def fetch_xml(url):
    if url not in (RSS_URL, RSS_FALLBACK_URL):
        require_official_url(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": "DatalokaNowcastEditorial/0.1 (BMKG official CAP)",
        "Accept": "application/xml,text/xml,application/rss+xml",
    })
    with urllib.request.urlopen(req, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"BMKG API responded HTTP {response.status}")
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("BMKG XML document too large")
    return raw


def text(parent, name):
    return (parent.findtext(name) or "").strip()


def instant(value):
    when = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("CAP timestamp has no timezone")
    return when


def fetch_rss():
    """Use the API path published on data.bmkg.go.id; retry the official
    RSS filename from BMKG's own code example on HTTP 404/405 only.
    No website HTML scraping and no third-party endpoints.
    """
    import urllib.error
    try:
        raw = fetch_xml(RSS_URL)
        parse_rss(raw)  # also reject a 200 HTML response
        return raw
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 405):
            raise
    except (ET.ParseError, ValueError):
        pass
    print("WARNING: primary BMKG CAP RSS endpoint unavailable; trying official rss.xml",
          file=sys.stderr)
    raw = fetch_xml(RSS_FALLBACK_URL)
    parse_rss(raw)
    return raw


def parse_rss(raw):
    root = ET.fromstring(raw)
    if root.tag != "rss":
        raise ValueError("Not a BMKG RSS document")
    items = []
    for item in root.findall("./channel/item"):
        url = text(item, "link")
        try:
            require_official_url(url)
        except ValueError:
            continue
        items.append({"url": url, "title": text(item, "title")})
    return items


def parse_cap(raw, url):
    require_official_url(url)
    root = ET.fromstring(raw)
    if root.tag != CAP_NS + "alert":
        raise ValueError("Invalid CAP document namespace")
    if text(root, CAP_NS+"status") != "Actual" or text(root, CAP_NS+"scope") != "Public":
        raise ValueError("CAP must be Actual and Public")
    if text(root, CAP_NS+"msgType") in ("Cancel", "Ack", "Error"):
        raise ValueError("Cancelled or non-alert CAP message")
    identifier = text(root, CAP_NS+"identifier")
    if not identifier:
        raise ValueError("CAP identifier missing")
    info = next((x for x in root.findall(CAP_NS+"info")
                 if text(x, CAP_NS+"language").lower().startswith("id")), None)
    if info is None:
        raise ValueError("No Indonesian CAP info")
    event = text(info, CAP_NS+"event")
    headline = text(info, CAP_NS+"headline")
    description = " ".join(text(info, CAP_NS+"description").split())
    areas = list(dict.fromkeys(text(x, CAP_NS+"areaDesc")
                               for x in info.findall(CAP_NS+"area")))
    areas = [a for a in areas if a]
    effective, expires = instant(text(info, CAP_NS+"effective")), instant(
        text(info, CAP_NS+"expires"))
    sent = instant(text(root, CAP_NS+"sent"))
    if expires <= effective or (expires-effective) > dt.timedelta(hours=12):
        raise ValueError("CAP expiry outside permitted range")
    if not event or not headline or not description or not areas:
        raise ValueError("CAP mandatory weather fields missing")
    # CAP references syntax is sender,identifier,sent. Keep a stable key
    # for updates that explicitly refer to an earlier warning.
    refs = text(root, CAP_NS+"references").split()
    original = refs[0].split(",")[1] if refs and len(refs[0].split(",")) >= 3 else identifier
    key = hashlib.sha256(original.encode("utf-8")).hexdigest()[:16]
    return {
        "key": key, "identifier": identifier, "url": url,
        "event": event, "headline": headline, "description": description,
        "region": ", ".join(areas), "issued": sent.isoformat(),
        "effective": effective.isoformat(), "expires": expires.isoformat(),
        "severity": text(info, CAP_NS+"severity"),
        "urgency": text(info, CAP_NS+"urgency"),
        "certainty": text(info, CAP_NS+"certainty"),
        "sender": text(info, CAP_NS+"senderName") or "BMKG",
    }


def active(entry, now):
    """Reject expired, future-dated, implausibly stale, or unverified alerts."""
    try:
        issued = instant(entry["issued"]).astimezone(UTC)
        expiry = instant(entry["expires"]).astimezone(UTC)
        start = instant(entry["effective"]).astimezone(UTC)
    except (ValueError, KeyError, TypeError):
        return False
    return (issued <= now + dt.timedelta(minutes=5)
            and now < expiry
            and start <= now + dt.timedelta(hours=6)
            and now >= issued - dt.timedelta(minutes=5)
            and entry["urgency"] not in ("Past", "Unknown")
            and entry["certainty"] not in ("Unlikely", "Unknown"))


def time_label(value):
    when = instant(value)
    offset = when.utcoffset()
    zone = {dt.timedelta(hours=7): "WIB",
            dt.timedelta(hours=8): "WITA",
            dt.timedelta(hours=9): "WIT"}.get(offset, "UTC")
    return f"{when:%H.%M} {zone}"


def date_label(value):
    when = instant(value)
    return f"{when.day} {MONTHS[when.month-1]} {when.year}"


def fingerprint(entry):
    keep = ("identifier", "event", "headline", "description", "region",
            "issued", "effective", "expires", "severity", "urgency", "certainty")
    return hash_value(json.dumps({x: entry[x] for x in keep},
                                 sort_keys=True, ensure_ascii=False))


def article(entry):
    region = entry["region"]
    event = entry["event"]
    date = date_label(entry["effective"])
    issued = time_label(entry["issued"])
    start = time_label(entry["effective"])
    end = time_label(entry["expires"])
    headline = f"BMKG: Peringatan {event} di {region}"
    if len(headline) > 125:
        # Headline CAP remains intact in the body and metadata.
        headline = f"BMKG Terbitkan Peringatan Dini Cuaca untuk {region}"
    source = html.escape(entry["url"], quote=True)
    desc = html.escape(entry["description"], quote=True)
    checked = dt.datetime.now(UTC).astimezone(instant(entry["issued"]).tzinfo)
    clean_region = html.escape(region, quote=True)
    clean_event = html.escape(event, quote=True)
    # Exactly five editorial paragraphs, retaining BMKG's complete description.
    content = (
        f'<p><strong>Dataloka.id</strong> - Badan Meteorologi, Klimatologi, '
        f'dan Geofisika (BMKG) mengeluarkan peringatan dini '
        f'<a href="https://dataloka.id/tag/cuaca">cuaca</a> '
        f'terkait {clean_event} untuk wilayah {clean_region} pada {date}.</p>'
        f'<p>Peringatan diterbitkan pukul {issued} dan berlaku sejak pukul '
        f'{start} hingga {end}, sesuai informasi resmi BMKG.</p>'
        f'<p>Wilayah yang disebut dalam peringatan tersebut meliputi '
        f'{clean_region}. BMKG merinci kondisi cuaca dan lokasi yang '
        f'berpotensi terdampak dalam keterangannya.</p>'
        f'<p>{desc}</p>'
        f'<p>Informasi ini merupakan peringatan dini yang memiliki masa berlaku '
        f'terbatas dan dapat diperbarui. Periksa <a href="{source}">'
        f'peringatan resmi BMKG</a> untuk kondisi terbaru.</p>'
        f'\n<p><strong>Sumber:</strong> '
        f'<a href="{source}">Badan Meteorologi, Klimatologi, dan '
        f'Geofisika (BMKG)</a>, diakses pada '
        f'{date_label(checked.isoformat())}.</p>'
        f'<!-- {MARKER}{entry["key"]} -->'
    )
    summary = (f"BMKG mengeluarkan peringatan dini {event} di {region} pada "
               f"{date}, berlaku pukul {start}–{end}. Periksa wilayah dan "
               "perkembangan terbaru.")
    if len(summary) > 280:
        summary = (f"Peringatan dini cuaca BMKG di {region} pada {date}, "
                   f"berlaku hingga {end}. Pantau rincian resminya.")[:280]
    title_seo = (f"Peringatan Dini Cuaca {region} {date} - BMKG")
    focus = f"peringatan dini cuaca {region}"
    when = instant(entry["issued"])
    slug = f"peringatan-dini-cuaca-{slugify(region)[:45].rstrip('-')}-{when:%Y-%m-%d}-{entry['key'][:8]}"
    return {
        "title": html.escape(headline, quote=True),
        "content": content, "excerpt": html.escape(summary, quote=True),
        "slug": slug, "comment_status": "closed",
        "tag_names": ["Featured", "BMKG", "Cuaca", "Peringatan"],
        "yoast_meta": {
            "_yoast_wpseo_focuskw": focus,
            "_yoast_wpseo_title": title_seo[:100],
            "_yoast_wpseo_metadesc": summary[:280],
        },
    }


class WeatherWordPress(WordPress):
    """Publish only when live story has image, Featured tag, and verified SEO."""

    def call(self, method, route, params=None, payload=None):
        # The parent publisher creates a draft, checks Yoast and then makes a
        # status-only POST to publish it. Fail closed if WordPress silently
        # ignored the Featured tag or the uploaded cover while saving the draft.
        if (method == "POST" and route.startswith("posts/") and
                isinstance(payload, dict) and payload == {"status": "publish"}):
            draft = self.by_id(int(route.split("/", 1)[1]))
            if draft.get("status") != "draft":
                raise RuntimeError("Weather post is not a verified draft; refusing publication")
            if not int(draft.get("featured_media") or 0):
                raise RuntimeError("Weather featured image missing on draft; refusing publication")
            featured_ids = self.resolve_tags(["Featured"])
            assigned = set(int(x) for x in (draft.get("tags") or []))
            if not featured_ids or not set(featured_ids).issubset(assigned):
                raise RuntimeError("Weather Featured tag missing on draft; refusing publication")
        try:
            return super().call(method, route, params=params, payload=payload)
        except RuntimeError as exc:
            # A POST is not safe to retry: WordPress may have committed the
            # draft before the client timed out. Query its stable slug instead.
            if (method == "POST" and route == "posts" and
                    isinstance(payload, dict) and
                    payload.get("status") == "draft" and
                    "network error on POST posts" in str(exc)):
                slug = payload.get("slug")
                if slug:
                    found = self.by_slug(slug)
                    if (found and found.get("slug") == slug and
                            found.get("content", {}).get("raw") == payload.get("content")
                            and found.get("status") == "draft"):
                        print(f"RECOVERED: timed-out draft POST saved by WP: {found['id']}",
                              flush=True)
                        return found
            raise

    def cover_image(self, entry):
        from dataloka_cuaca_image import render
        name = "dataloka-cuaca-" + entry["key"]
        found = self.call("GET", "media", {
            "slug": name, "context": "edit", "per_page": 2})
        if found:
            return int(found[0]["id"])
        jpg = render(entry)
        req = urllib.request.Request(
            "https://dataloka.id/wp-json/wp/v2/media",
            data=jpg, method="POST",
            headers={
                "Authorization": self.authorization,
                "Accept": "application/json",
                "Content-Type": "image/jpeg",
                "Content-Disposition": f'attachment; filename="{name}.jpg"',
                "User-Agent": "DatalokaNowcastEditorial/0.1",
            })
        with urllib.request.urlopen(req, timeout=40) as response:
            item = json.loads(response.read(1_000_000))
        media_id = int(item["id"])
        caption = (f"Ilustrasi editorial Dataloka untuk peringatan dini "
                   f"{entry['event']} di {entry['region']}. Sumber: BMKG.")
        self.call("POST", f"media/{media_id}", payload={
            "alt_text": caption, "title": caption, "caption": caption})
        return media_id


def load_state():
    if not STATE.exists():
        return {"version": 1, "alerts": {}}
    loaded = json.loads(STATE.read_text(encoding="utf-8"))
    if loaded.get("version") != 1 or not isinstance(loaded.get("alerts"), dict):
        raise ValueError("Invalid weather ledger; aborting")
    return loaded


def process(entries, mode, now=None, wp=None, state=None):
    if mode not in ("fixture", "dry-run", "live"):
        raise ValueError("Unsupported mode")
    now = now or dt.datetime.now(UTC)
    injected_state = state is not None  # offline tests never touch the real ledger
    state = state if state is not None else load_state()
    suitable = [x for x in entries if active(x, now)]
    suitable.sort(key=lambda x: instant(x["issued"]), reverse=True)
    updated = 0
    failures = []
    for entry in suitable:
        old = state["alerts"].get(entry["key"], {})
        if (old.get("fingerprint") == fingerprint(entry) and
                old.get("editorial_version") == EDITORIAL_VERSION):
            continue
        age_minutes = (now - instant(entry["issued"]).astimezone(UTC)).total_seconds()/60
        if not old.get("post_id") and age_minutes > MAX_NEW_ALERT_AGE_MINUTES:
            continue
        payload = article(entry)
        print(f"{mode}: {payload['title']} | {entry['url']}", flush=True)
        if mode != "live":
            updated += 1
            if updated >= MAX_ALERTS_PER_RUN:
                break
            continue
        try:
            mapping = wp.save(
                payload, old, "publish",
                f"<!-- {MARKER}{entry['key']} -->",
                event=entry)
            state["alerts"][entry["key"]] = {
                **mapping, "fingerprint": fingerprint(entry),
                "editorial_version": EDITORIAL_VERSION,
                "expires": entry["expires"]}
            updated += 1
            if updated >= MAX_ALERTS_PER_RUN:
                break
        except EditorialConflict as exc:
            print(f"SKIP: editorial revision protected: {exc}", file=sys.stderr)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            print(f"ERROR: failed to publish weather alert {entry['key']}: {exc}",
                  file=sys.stderr)
            failures.append(entry["key"])
            # Avoid flooding WordPress after the first failed write.
            break
    if mode == "live" and not injected_state:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False)+"\n",
                         encoding="utf-8")
    if failures:
        raise RuntimeError(f"Failed live weather alerts: {','.join(failures)}")
    return updated


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("fixture", "dry-run", "live"),
                   default="fixture")
    args = p.parse_args()
    if args.mode == "fixture":
        # Offline parsing test; samples are published as code examples by BMKG.
        sample = ROOT / "tests" / "fixtures" / "nowcast-sample.xml"
        doc = parse_cap(sample.read_bytes(),
                        "https://www.bmkg.go.id/alerts/nowcast/id/CJB20251013001_alert.xml")
        jpg = __import__("dataloka_cuaca_image").render(doc)
        print(f"BMKG fixture parsed and 1200x675 cover generated ({len(jpg)} bytes)")
        return
    if args.mode == "live" and os.environ.get("BMKG_NOWCAST_AUTHORIZED") != "true":
        raise RuntimeError("BMKG written authorization not confirmed for live WordPress publication")
    rss = parse_rss(fetch_rss())
    entries = []
    for item in rss[:45]:
        try:
            entries.append(parse_cap(fetch_xml(item["url"]), item["url"]))
        except (ValueError, ET.ParseError, OSError, RuntimeError) as exc:
            print(f"WARNING: skipped CAP detail: {exc}", file=sys.stderr)
    if rss and not entries:
        raise RuntimeError("Official BMKG RSS returned no valid CAP details")
    wp = (WeatherWordPress(os.getenv("WP_USERNAME"), os.getenv("WP_APP_PASSWORD"))
          if args.mode == "live" else None)
    count = process(entries, args.mode, wp=wp)
    print(f"{count} weather alerts processed in {args.mode} mode")


if __name__ == "__main__":
    main()
