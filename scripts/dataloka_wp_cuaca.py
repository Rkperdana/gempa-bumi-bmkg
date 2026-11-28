#!/usr/bin/env python3
"""BMKG CAP nowcasting -> Dataloka live WordPress publisher, isolated from earthquake automation.

Live mode publishes only validated active CAP alerts with a cover image and
verified Yoast meta. No Featured tag is assigned to weather alerts. Requires BMKG authorization and WordPress credentials.
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
import time
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
WIB = dt.timezone(dt.timedelta(hours=7))
MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni",
          "Juli", "Agustus", "September", "Oktober", "November", "Desember")
WEEKDAYS = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
MARKER = "dataloka-nowcast:"
EDITORIAL_VERSION = 5  # One article per province, local date, and time period
MAX_ALERTS_PER_RUN = 5
_last_request = 0.0
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
    global _last_request
    time.sleep(max(0, 1.1 - (time.monotonic() - _last_request)))
    _last_request = time.monotonic()
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


def dated_time_label(value):
    when = instant(value)
    return f"pukul {time_label(value)} pada {WEEKDAYS[when.weekday()]}, {date_label(value)}"


def cap_details(entry):
    """Extract only fields explicitly present in the official CAP description."""
    description = entry["description"]
    phrase_match = re.match(r"(.{3,100}?)\s+akan terjadi pada\b", description, re.I)
    phenomenon = (phrase_match.group(1).strip() if phrase_match
                  else str(entry["event"]).strip())
    areas_match = re.search(r"\bkhususnya di\s+(.+?)\.\s+Kondisi ini\b",
                            description, re.I)
    areas = []
    if areas_match:
        names = re.sub(r",?\s+dan\s+", ", ", areas_match.group(1))
        for name in names.split(","):
            name = name.strip()
            if name and len(name) <= 80 and name.casefold() not in {
                    item.casefold() for item in areas}:
                areas.append(name)
        if len(areas) > 250:
            areas = []
    impact_match = re.search(
        r"Kondisi ini berpotensi menimbulkan dampak berupa\s+(.+?)\.\s+Masyarakat\b",
        description, re.I)
    advice_match = re.search(r"\bMasyarakat dihimbau\s+(.+?)\.\s+Kondisi diperkirakan\b",
                             description, re.I)
    return phenomenon, areas, (impact_match.group(1).strip() if impact_match else None), (
        advice_match.group(1).strip() if advice_match else None)


def area_label(value):
    roman = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}
    return " ".join(word if word in roman else word.title() for word in value.split())


def media_copy(entry):
    phrase, _, _, _ = cap_details(entry)
    caption = f"Ilustrasi {phrase.lower()}."
    return {
        "alt_text": f"Peringatan dini cuaca BMKG {display_region(entry)}",
        "title": caption,
        "caption": caption,
    }


def fingerprint(entry):
    keep = ("identifier", "event", "headline", "description", "region",
            "issued", "effective", "expires", "severity", "urgency", "certainty")
    return hash_value(json.dumps({x: entry[x] for x in keep},
                                 sort_keys=True, ensure_ascii=False))


def province_day_key(entry):
    """Legacy daily key retained for reading articles published before period mode."""
    province = canonical_province(entry)
    day = instant(entry["issued"]).astimezone(WIB).date().isoformat()
    return hashlib.sha256(f"{province}|{day}".encode("utf-8")).hexdigest()[:20]


def canonical_province(entry):
    province = " ".join(html.unescape(str(entry["region"])).split()).casefold()
    aliases = {
        "kep riau": "kepulauan riau", "kep. riau": "kepulauan riau",
        "dki": "jakarta", "d.k.i. jakarta": "jakarta",
        "dki jakarta": "jakarta",
        "kepulauan bangka belitung": "kep. bangka belitung",
        "di yogyakarta": "diy", "d.i. yogyakarta": "diy",
        "daerah istimewa yogyakarta": "diy",
        "ntb": "nusa tenggara barat", "ntt": "nusa tenggara timur",
        "babel": "kepulauan bangka belitung",
    }
    return aliases.get(province, province)


def period_details(entry):
    """Use the CAP's local time; 00.00–05.59 belongs to the previous night."""
    issued = instant(entry["issued"])
    if issued.utcoffset() not in (dt.timedelta(hours=7), dt.timedelta(hours=8),
                                  dt.timedelta(hours=9)):
        issued = issued.astimezone(WIB)
    hour = issued.hour
    if hour < 6:
        return (issued.date() - dt.timedelta(days=1), "Malam")
    if hour < 12:
        return (issued.date(), "Pagi")
    if hour < 15:
        return (issued.date(), "Siang")
    if hour < 18:
        return (issued.date(), "Sore")
    return (issued.date(), "Malam")


def province_period_key(entry):
    day, period = period_details(entry)
    value = f"{canonical_province(entry)}|{day.isoformat()}|{period.casefold()}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def display_region(entry):
    """BMKG's CJK feed covers Jabodetabek, including areas outside Jakarta."""
    region = entry["region"]
    if (region.strip().casefold() in ("jakarta", "dki jakarta")
            and re.search(r"/CJK[0-9]+_alert\.xml$", entry["url"])):
        return "Jabodetabek"
    return region


def article(entries, marker_key=None):
    """Build a source-grounded provincial bulletin for one local time period."""
    if isinstance(entries, dict):
        entries = [entries]
    entries = sorted(entries, key=lambda e: (instant(e["issued"]), e["key"]))
    if not entries:
        raise ValueError("Cannot build a weather article without CAP alerts")
    latest = entries[-1]
    region = display_region(latest)
    event = latest["event"]
    period_day, period = period_details(latest)
    date = f"{period_day.day} {MONTHS[period_day.month-1]} {period_day.year}"
    issued_at = instant(latest["issued"])
    expires_at = instant(latest["expires"])
    issued, start, end = (time_label(latest[key]) for key in ("issued", "effective", "expires"))
    phenomenon, areas, impact, advice = cap_details(latest)
    clean_region = html.escape(region, quote=True)
    clean_event = html.escape(event, quote=True)
    clean_phenomenon = html.escape(phenomenon, quote=True)
    headline_base = f"BMKG: Peringatan Dini Cuaca {region} {date} {period}"
    headline = f"{headline_base}, Waspada {event}"
    if len(headline) > 150:
        headline = headline_base

    if issued_at.date() != period_day:
        lead_time = (f"pada {WEEKDAYS[issued_at.weekday()]} dini hari "
                     f"({issued_at:%d/%m/%Y}), dalam periode malam {date}")
    else:
        lead_time = (f"pada {WEEKDAYS[issued_at.weekday()]} "
                     f"({issued_at:%d/%m/%Y}) {period.lower()}")
    end_detail = (dated_time_label(latest["expires"])
                  if expires_at.date() != issued_at.date() else f"pukul {end}")

    now = dt.datetime.now(UTC)
    history = ""
    if len(entries) > 1:
        items = "".join(
            f'<li><strong>{date_label(item["issued"])} pukul '
            f'{time_label(item["issued"])}</strong> — '
            f'{html.escape(item["event"], quote=True)}; '
            f'berlaku {time_label(item["effective"])}–{time_label(item["expires"])}. '
            f'{html.escape(item["description"], quote=True)}</li>'
            for item in reversed(entries)
        )
        history = f'<h2>Riwayat Peringatan BMKG pada Periode {period}</h2><ul>{items}</ul>'
    source_urls = sorted({item["url"] for item in entries})
    links = ", ".join(
        f'<a href="{html.escape(url, quote=True)}">dokumen peringatan BMKG</a>'
        for url in source_urls
    )
    area_note = (
        '<p><em>Catatan wilayah:</em> Peringatan BMKG berkode Jabodetabek '
        'dapat mencakup wilayah di luar DKI Jakarta. Rincian kecamatan '
        'mengikuti isi peringatan resmi.</p>'
        if region == "Jabodetabek" else ""
    )
    area_heading = f'<h2>Wilayah {clean_region} yang Berpotensi {clean_event}</h2>'
    if areas:
        labels = [area_label(name) for name in areas]
        listed = (labels[0] if len(labels) == 1 else
                  ", ".join(labels[:-1]) + ", dan " + labels[-1])
        area_body = (f'<p>{clean_phenomenon} berpotensi terjadi di {len(areas)} '
                     f'kecamatan di {clean_region}. Wilayah tersebut meliputi '
                     f'{html.escape(listed, quote=True)}.</p>')
    else:
        # Unrecognized CAP wording is displayed faithfully without a guessed count.
        area_body = f'<p>{html.escape(latest["description"], quote=True)}</p>'
        impact = advice = None
    impact_html = (f'<h2>Potensi Dampak Cuaca Buruk di {clean_region}</h2>'
                   f'<p>Menurut BMKG, kondisi ini berpotensi menimbulkan dampak '
                   f'berupa {html.escape(impact, quote=True)}.</p>' if impact else "")
    advice_html = (f'<p>BMKG mengimbau masyarakat '
                   f'{html.escape(advice, quote=True)}.</p>' if advice else "")
    content = (
        f'<p><strong>Dataloka.id</strong> – Badan Meteorologi, Klimatologi, '
        f'dan Geofisika (BMKG) mengeluarkan peringatan dini cuaca {clean_region} '
        f'{lead_time}. {clean_phenomenon} berpotensi terjadi di sejumlah wilayah '
        f'hingga {end_detail}.</p>'
        f'<p>Berdasarkan pembaruan informasi BMKG pada pukul {issued}, '
        f'peringatan tersebut berlaku mulai pukul {start} hingga {end_detail}.</p>'
        f'{area_heading}{area_body}'
        f'{area_note}'
        f'{impact_html}{advice_html}'
        f'<h2>Masa Berlaku Peringatan Dini Cuaca BMKG</h2>'
        f'<p>Berdasarkan informasi terbaru BMKG, peringatan untuk {clean_region} '
        f'berlaku hingga {dated_time_label(latest["expires"])}.</p>'
        f'<p>Peringatan dini cuaca memiliki masa berlaku terbatas dan dapat '
        f'berubah mengikuti perkembangan kondisi atmosfer. Pembaca dapat '
        f'memantau pembaruan melalui kanal resmi BMKG.</p>'
        f'{history}'
        f'<p><strong>Sumber:</strong> Badan Meteorologi, Klimatologi, dan '
        f'Geofisika (BMKG); {links}. Diperiksa pada '
        f'{date_label(now.astimezone(WIB).isoformat())}.</p>'
        f'<!-- {MARKER}{marker_key or latest["key"]} -->'
    )
    count_copy = (f"Sebanyak {len(areas)} kecamatan berpotensi mengalami "
                  if areas else "Potensi ")
    summary = (f"Peringatan dini BMKG {region} {date} {period.lower()}. "
               f"{count_copy}{phenomenon.lower()} hingga pukul {end}.")
    if len(summary) > 280:
        summary = (f"Peringatan dini cuaca BMKG {region} {date} {period.lower()}, "
                   f"berlaku hingga pukul {end}.")[:280]
    title_seo = headline_base
    focus = f"peringatan dini cuaca {region}"
    # Preserve already-published 28 Nov ISO slugs; later periods use readable dates.
    date_slug = (period_day.isoformat() if period_day <= dt.date(2026, 11, 28)
                 else f"{period_day.day}-{MONTHS[period_day.month-1].lower()}-{period_day.year}")
    slug = (f"peringatan-dini-cuaca-{slugify(canonical_province(latest))[:45].rstrip('-')}-"
            f"{date_slug}-{period.casefold()}")
    return {
        "title": html.escape(headline, quote=True),
        "content": content, "excerpt": html.escape(summary, quote=True),
        "slug": slug, "comment_status": "closed",
        "tag_names": ["BMKG", "Cuaca", "Peringatan"],
        "yoast_meta": {
            "_yoast_wpseo_focuskw": focus,
            "_yoast_wpseo_title": title_seo[:100],
            "_yoast_wpseo_metadesc": summary[:280],
        },
    }

class WeatherWordPress(WordPress):
    """Require a featured *image*, but do not require the Featured *tag*."""

    def save(self, payload, ledger, status, marker, event=None):
        if (event and display_region(event) != event["region"]
                and ledger.get("post_id") and ledger.get("last_wp_digest")):
            post = self.by_id(ledger["post_id"])
            if (hash_value(post.get("content", {}).get("raw", ""))
                    == ledger["last_wp_digest"]
                    and int(post.get("featured_media") or 0)
                    == int(ledger.get("media_id") or 0)):
                payload = dict(payload, featured_media=self.cover_image(event))
        return super().save(payload, ledger, status, marker, event=event)

    def call(self, method, route, params=None, payload=None):
        # The parent publisher creates a draft, verifies Yoast and then switches
        # to publish. The image is required; the Featured taxonomy term is not.
        if (method == "POST" and route.startswith("posts/") and
                isinstance(payload, dict) and payload == {"status": "publish"}):
            draft = self.by_id(int(route.split("/", 1)[1]))
            if draft.get("status") != "draft":
                raise RuntimeError("Weather post is not a verified draft; refusing publication")
            if not int(draft.get("featured_media") or 0):
                raise RuntimeError("Weather featured image missing on draft; refusing publication")
        if (method == "POST" and (payload or {}).get("status") == "publish"
                and getattr(self, "current_alert", None)):
            verify_current(self.current_alert)
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

    def remove_featured_tag(self, post_id, marker, expected_digest):
        """Remove only the Featured taxonomy tag from a verified bot-owned post.

        Never overwrite an editor's body, title, image, SEO, or other tags.
        Existing bot-ledger ownership and unchanged text must be verified first.
        """
        post = self.by_id(post_id)
        raw = post.get("content", {}).get("raw", "")
        if (not expected_digest or marker not in raw or
                hash_value(raw) != expected_digest):
            raise EditorialConflict("Existing weather post was edited or lacks bot marker")
        tags = [int(tag) for tag in (post.get("tags") or [])]
        matches = self.call("GET", "tags", {"search": "Featured", "per_page": 100})
        featured = {
            int(term["id"]) for term in matches
            if html.unescape(str(term.get("name", ""))).strip().casefold() == "featured"
            or str(term.get("slug", "")).strip().casefold() == "featured"
        }
        remaining = [tag for tag in tags if tag not in featured]
        if len(remaining) == len(tags):
            return True
        self.call("POST", f"posts/{int(post_id)}", payload={"tags": remaining})
        confirmed = self.by_id(post_id)
        actual = [int(tag) for tag in (confirmed.get("tags") or [])]
        if (set(actual) != set(remaining) or
                hash_value(confirmed.get("content", {}).get("raw", "")) != expected_digest):
            raise RuntimeError("WordPress did not persist a tags-only removal safely")
        print(f"Removed Featured taxonomy tag from weather post {post_id}", flush=True)
        return True

    def cover_image(self, entry):
        from dataloka_cuaca_image import render
        name = "dataloka-cuaca-" + entry.get("province_period_key", entry["key"])
        if display_region(entry) != entry["region"]:
            name += "-jabodetabek"
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
        self.call("POST", f"media/{media_id}", payload=media_copy(entry))
        return media_id


def load_state():
    if not STATE.exists():
        return {"version": 1, "alerts": {}, "province_days": {}, "province_periods": {}}
    loaded = json.loads(STATE.read_text(encoding="utf-8"))
    if loaded.get("version") != 1 or not isinstance(loaded.get("alerts"), dict):
        raise ValueError("Invalid weather ledger; aborting")
    loaded.setdefault("province_days", {})
    if not isinstance(loaded["province_days"], dict):
        raise ValueError("Invalid provincial weather ledger; aborting")
    loaded.setdefault("province_periods", {})
    if not isinstance(loaded["province_periods"], dict):
        raise ValueError("Invalid period weather ledger; aborting")
    return loaded

def write_state(state):
    tmp = STATE.with_suffix(".tmp")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(STATE)


class AlertChanged(ValueError):
    pass


def cancelled_ids(raw):
    root = ET.fromstring(raw)
    if (root.tag != CAP_NS+"alert" or text(root, CAP_NS+"msgType") != "Cancel"
            or text(root, CAP_NS+"status") != "Actual" or text(root, CAP_NS+"scope") != "Public"):
        return set()
    return {ref.split(",")[1] for ref in text(root, CAP_NS+"references").split()
            if len(ref.split(",")) == 3}


def verify_current(entry):
    urls = {item["url"] for item in parse_rss(fetch_rss())}
    if entry["url"] not in urls:
        raise AlertChanged("Alert has left the active BMKG feed")
    raw = fetch_xml(entry["url"])
    try:
        current = parse_cap(raw, entry["url"])
    except ValueError as exc:
        raise AlertChanged(str(exc)) from exc
    if fingerprint(current) != fingerprint(entry) or not active(current, dt.datetime.now(UTC)):
        raise AlertChanged("BMKG revised or expired this alert")


def collect(entries, state, now, failed_urls=(), cancelled=()):
    pending = state.setdefault("pending", {})
    history = state.setdefault("skipped", {})
    newest = {}
    for entry in entries:
        key = entry["key"]
        if key not in newest or instant(entry["issued"]) >= instant(newest[key]["issued"]):
            newest[key] = entry
    cancelled_keys = {hashlib.sha256(identifier.encode()).hexdigest()[:16] for identifier in cancelled}
    for key, entry in list(pending.items()):
        if key in cancelled_keys or entry["identifier"] in cancelled:
            history[key] = {"region": entry["region"], "expires": entry["expires"], "reason": "cancelled"}
            del pending[key]
            continue
        if key not in newest and (entry["url"] not in failed_urls or instant(entry["expires"]) <= now):
            history[key] = {"region": entry["region"], "expires": entry["expires"],
                            "reason": "expired" if instant(entry["expires"]) <= now else "withdrawn"}
            del pending[key]
    for key, entry in newest.items():
        old = state["alerts"].get(key, {})
        if key in cancelled_keys or entry["identifier"] in cancelled:
            history[key] = {"region": entry["region"], "expires": entry["expires"], "reason": "cancelled"}
            pending.pop(key, None)
        elif history.get(key, {}).get("fingerprint") == fingerprint(entry):
            pending.pop(key, None)
        elif not active(entry, now):
            history[key] = {"region": entry["region"], "expires": entry["expires"],
                            "reason": "expired" if instant(entry["expires"]) <= now else "inactive"}
            pending.pop(key, None)
        elif (old.get("fingerprint") == fingerprint(entry)
              and (old.get("post_id") or old.get("editorial_version") in (2, 3, 4, 5))):
            # A format rollout must not republish already-covered CAP messages.
            pending.pop(key, None)
        else:
            pending[key] = entry
            history.pop(key, None)
    state["unread_urls"] = sorted(failed_urls)
    if not failed_urls:
        state["last_checked_at"] = now.isoformat()


def process(entries, mode, now=None, wp=None, state=None):
    if mode not in ("fixture", "dry-run", "live"):
        raise ValueError("Unsupported mode")
    def clock():
        return now or dt.datetime.now(UTC)
    persistent = mode == "live" and state is None
    state = state if state is not None else load_state()
    if entries is not None:
        collect(entries, state, clock())
    pending = state.setdefault("pending", {})
    province_periods = state.setdefault("province_periods", {})
    last_served = state.setdefault("last_served", {})
    candidates = [e for e in pending.values() if e["url"] not in state.get("unread_urls", [])]
    grouped = {}
    for entry in candidates:
        grouped.setdefault(province_period_key(entry), []).append(entry)
    groups = list(grouped.items())
    served = {}
    updated = 0
    failures = []
    while groups and updated < MAX_ALERTS_PER_RUN:
        group_key, group_entries = min(
            groups,
            key=lambda item: (
                served.get(item[1][0]["region"], 0),
                last_served.get(item[1][0]["region"], ""),
                min(instant(e["expires"]) for e in item[1]),
                item[0],
            ),
        )
        groups.remove((group_key, group_entries))
        region = group_entries[0]["region"]
        eligible = [e for e in group_entries if active(e, clock())]
        if not eligible:
            for item in group_entries:
                pending.pop(item["key"], None)
                state.setdefault("skipped", {})[item["key"]] = {
                    "region": region, "expires": item["expires"], "reason": "expired"
                }
            continue

        entry = max(eligible, key=lambda e: (instant(e["issued"]), e["key"]))
        served[region] = served.get(region, 0) + 1
        old = province_periods.get(group_key, {})
        marker_key = old.get("marker_key")
        if not old:
            # Recover only the same period; an earlier period needs a new post.
            for candidate in sorted(
                eligible, key=lambda e: (instant(e["issued"]), e["key"]), reverse=True
            ):
                prior = state["alerts"].get(candidate["key"], {})
                if prior.get("post_id") and prior.get("province_period_key") == group_key:
                    old = prior
                    marker_key = prior.get("marker_key") or candidate["key"]
                    break
        marker_key = marker_key or entry["key"]
        if old.get("post_id"):
            prior_entries = old.get("entries") or eligible
            prior = max(prior_entries, key=lambda e: (instant(e["issued"]), e["key"]))
            prior_day, prior_period = period_details(prior)
            prior_date = f"{prior_day.day} {MONTHS[prior_day.month-1]} {prior_day.year}"
            prior_region = display_region(prior)
            old = dict(old, bot_previous_titles=[
                f"BMKG: Peringatan {prior['event']} di {prior['region']}",
                f"BMKG Terbitkan Peringatan Dini Cuaca untuk {prior['region']}",
                f"Peringatan Dini Cuaca {prior['region']} "
                f"{date_label(prior['issued'])} - BMKG",
                f"Peringatan Dini Cuaca {prior_region} {prior_date} {prior_period} - BMKG",
                html.unescape(article(prior)["title"]),
            ])

        combined = {}
        for prior_entry in old.get("entries", []):
            if province_period_key(prior_entry) == group_key:
                combined[prior_entry["key"]] = prior_entry
        for current_entry in eligible:
            combined[current_entry["key"]] = current_entry
        article_entries = sorted(
            combined.values(), key=lambda e: (instant(e["issued"]), e["key"])
        )
        payload = article(article_entries, marker_key)
        print(
            f"{mode}: {payload['title']} | {len(article_entries)} alert(s) | "
            f"{entry['url']}",
            flush=True,
        )
        if mode != "live":
            updated += 1
            continue

        article_entry = dict(entry, province_period_key=group_key)
        try:
            wp.current_alert = entry
            mapping = wp.save(
                payload, old, "publish", f"{MARKER}{marker_key}", event=article_entry
            )
            period_day, period = period_details(entry)
            province_periods[group_key] = {
                **mapping,
                "marker_key": marker_key,
                "region": region,
                "day": period_day.isoformat(),
                "period": period,
                "latest_key": entry["key"],
                "entries": article_entries,
                "editorial_version": EDITORIAL_VERSION,
            }
            for item in group_entries:
                pending.pop(item["key"], None)
                if item not in eligible:
                    state.setdefault("skipped", {})[item["key"]] = {
                        "region": item["region"], "expires": item["expires"],
                        "reason": "expired",
                    }
                    continue
                record = state["alerts"].get(item["key"], {})
                record.update({
                    "fingerprint": fingerprint(item),
                    "editorial_version": EDITORIAL_VERSION,
                    "province_period_key": group_key,
                    "expires": item["expires"],
                })
                record.update(mapping)
                record["marker_key"] = marker_key
                state["alerts"][item["key"]] = record
            last_served[region] = clock().isoformat()
            if persistent:
                write_state(state)
            updated += 1
        except AlertChanged as exc:
            print(f"SKIP {region}: {exc}", file=sys.stderr)
            pending.pop(entry["key"], None)
            state.setdefault("skipped", {})[entry["key"]] = {
                "region": region, "expires": entry["expires"], "reason": str(exc)
            }
        except EditorialConflict as exc:
            # Never replace an editor's changes to a period's canonical post.
            for item in group_entries:
                pending.pop(item["key"], None)
                state.setdefault("skipped", {})[item["key"]] = {
                    "region": region, "expires": item["expires"],
                    "reason": "editorial conflict", "fingerprint": fingerprint(item),
                }
            print(f"SKIP: editorial revision protected: {exc}", file=sys.stderr)
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            print(f"ERROR: failed to publish weather alert {entry['key']}: {exc}",
                  file=sys.stderr)
            failures.append(entry["key"])
            # Avoid flooding WordPress after the first failed write.
            break
    if persistent:
        write_state(state)
    print(f"Queue: {len(pending)} pending, {updated} province-period article(s) processed")
    if failures:
        raise RuntimeError(f"Failed live weather alerts: {','.join(failures)}")
    return updated

def cleanup_existing_featured(wp, state=None):
    """Gradually remove Featured from old, unmodified, bot-owned weather posts.

    One post per run limits WordPress traffic. Human edits are never overwritten.
    """
    loaded = state if state is not None else load_state()
    for key, record in loaded["alerts"].items():
        if record.get("featured_tag_removed") or not record.get("post_id"):
            continue
        marker = f"<!-- {MARKER}{key} -->"
        try:
            wp.remove_featured_tag(record["post_id"], marker,
                                   record.get("last_wp_digest"))
        except EditorialConflict as exc:
            print(f"SKIP weather post {record['post_id']}: {exc}", file=sys.stderr)
            continue
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            print(f"WARNING: weather Featured cleanup delayed: {exc}", file=sys.stderr)
            break
        record["featured_tag_removed"] = True
        if state is None:
            STATE.write_text(json.dumps(loaded, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        return 1
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("fixture", "dry-run", "collect", "publish-queue", "live"),
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
    if args.mode in ("live", "publish-queue") and os.environ.get("BMKG_NOWCAST_AUTHORIZED") != "true":
        raise RuntimeError("BMKG written authorization not confirmed for live WordPress publication")
    if args.mode != "publish-queue":
        urls = dict.fromkeys(item["url"] for item in parse_rss(fetch_rss()))
        entries, failed, cancelled = [], [], set()
        for url in urls:
            try:
                raw = fetch_xml(url)
                root = ET.fromstring(raw)
                cancelled.update(cancelled_ids(raw))
                if text(root, CAP_NS+"msgType") in ("Cancel", "Ack", "Error"):
                    continue
                entries.append(parse_cap(raw, url))
            except (ValueError, ET.ParseError, OSError, RuntimeError) as exc:
                failed.append(url)
                print(f"WARNING: could not validate {url}: {exc}", file=sys.stderr)
        state = load_state()
        collect(entries, state, dt.datetime.now(UTC), failed, cancelled)
        print(f"BMKG: {len(urls)} URLs, {len(entries)} parsed, {len(failed)} unread, "
              f"{len(state['pending'])} queued")
        if args.mode == "dry-run":
            process(None, "dry-run", state=state)
            return
        write_state(state)
        if failed and not entries:
            raise RuntimeError("No readable CAP details this cycle")
        if args.mode == "collect":
            return
    wp = WeatherWordPress(os.getenv("WP_USERNAME"), os.getenv("WP_APP_PASSWORD"))
    count = process(None, "live", wp=wp)
    cleanup_existing_featured(wp)
    print(f"{count} weather alerts processed in {args.mode} mode")


if __name__ == "__main__":
    main()
