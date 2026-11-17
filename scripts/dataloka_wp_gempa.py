#!/usr/bin/env python3
"""Isolated BMKG -> Dataloka.id publisher. NEVER targets Pirsadata.

Runs with Python standard library. Credentials are GitHub Actions secrets.
Never create backdated posts on initial startup. Never overwrite human edits.
"""
from __future__ import annotations
import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import unicodedata

UTC = dt.timezone.utc
WIB = dt.timezone(dt.timedelta(hours=7))
BASE = "https://data.bmkg.go.id/DataMKG/TEWS/"
FEEDS = ("gempadirasakan.json", "gempaterkini.json", "autogempa.json")
ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "dataloka-wp-state.json"
WP_URL = "https://dataloka.id"
MARKER = "dataloka-bmkg:"
YOAST_KEYS = ("_yoast_wpseo_focuskw", "_yoast_wpseo_title", "_yoast_wpseo_metadesc")


def timestamp(value):
    value = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Missing timezone")
    return value.astimezone(UTC)


def numeral(value):
    return float(str(value).replace(",", "."))


def magnitude(value):
    return f"{float(value):.1f}".replace(".", ",")


def normalize(raw, feed):
    instant = timestamp(raw["DateTime"])
    lat, lon = map(numeral, str(raw["Coordinates"]).split(","))
    mag = numeral(raw["Magnitude"])
    depth_match = re.search(r"[0-9.,]+", str(raw["Kedalaman"]))
    if not depth_match:
        raise ValueError("Invalid depth")
    depth = numeral(depth_match.group())
    region = str(raw.get("Wilayah") or "").strip()
    if not region or not (-90 <= lat <= 90 and -180 <= lon <= 180 and
                          0 <= mag <= 10 and 0 <= depth <= 900):
        raise ValueError("Invalid BMKG earthquake")
    # BMKG public feeds have no permanent immutable event ID.
    key = f"{instant:%Y%m%dT%H%M%S}:{lat:.2f}:{lon:.2f}"
    return {
        "key": hashlib.sha1(key.encode()).hexdigest()[:14],
        "datetime": instant.isoformat().replace("+00:00", "Z"),
        "magnitude": mag, "depth_km": depth,
        "lat": lat, "lon": lon, "region": region,
        "potential": str(raw.get("Potensi") or "").strip(),
        "felt_info": str(raw.get("Dirasakan") or "").strip(),
        "felt": bool(raw.get("Dirasakan")) or feed == "gempadirasakan.json",
        "sources": [feed],
    }


def same_event(a, b):
    sec = abs((timestamp(a["datetime"]) - timestamp(b["datetime"])).total_seconds())
    x = (float(a["lon"]) - float(b["lon"])) * math.cos(
        math.radians((float(a["lat"]) + float(b["lat"])) / 2))
    y = float(a["lat"]) - float(b["lat"])
    km = math.hypot(x, y) * 111.2
    return (sec <= 2 and km <= 50) or (
        sec <= 45 and km <= 10 and
        abs(float(a["magnitude"]) - float(b["magnitude"])) <= .3)


def merge(a, b):
    result = dict(a)
    for field in ("datetime", "magnitude", "depth_km", "lat", "lon", "region"):
        result[field] = b[field]
    result["sources"] = sorted(set(a.get("sources", [])) | set(b.get("sources", [])))
    result["felt"] = bool(a.get("felt") or b.get("felt"))
    result["felt_info"] = b.get("felt_info") or a.get("felt_info", "")
    if b.get("potential"):
        result["potential"] = b["potential"]
    return result


def confirmed_no_tsunami(event):
    text = str(event.get("potential") or "").lower()
    match = re.search(r"\b(tidak|tak)\s+berpotensi\s+tsunami\b", text)
    return bool(match) and "berpotensi tsunami" not in (
        text[:match.start()] + text[match.end():])


def status_for(event, mode):
    """M5.5+ always qualifies for live publication, regardless of tsunami status.

    Tsunami potential is a factual field in the article; it must never be
    interpreted as a reason to suppress the official earthquake report.
    """
    if mode == "live" and event["magnitude"] >= 5.5:
        return "publish"
    return "draft"


def fetch_feed(feed):
    req = urllib.request.Request(BASE + feed, headers={
        "User-Agent": "Dataloka BMKG WordPress Publisher/1.0",
        "Accept": "application/json",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=25) as response:
        if response.status != 200:
            raise RuntimeError(f"BMKG HTTP {response.status}")
        return json.loads(response.read(250_000).decode("utf-8-sig"))


def get_events():
    results = []
    for feed in FEEDS:
        doc = fetch_feed(feed)
        raw = doc.get("Infogempa", {}).get("gempa")
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list) or not raw:
            raise ValueError(f"Empty BMKG feed: {feed}")
        valid = 0
        for item in raw:
            try:
                event = normalize(item, feed)
            except (ValueError, KeyError, TypeError) as exc:
                print(f"Skipping invalid BMKG entry in {feed}: {exc}", file=sys.stderr)
                continue
            valid += 1
            idx = next((i for i, x in enumerate(results) if same_event(x, event)), None)
            if idx is None:
                results.append(event)
            else:
                results[idx] = merge(results[idx], event)
        if valid == 0:
            raise ValueError(f"No valid earthquakes in {feed}")
    return results


def read_state():
    if not STATE.exists():
        return {"version": 1, "events": [], "daily": {}}
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("version") != 1 or not isinstance(state.get("events"), list):
        raise ValueError("Invalid Dataloka state; refusing to overwrite")
    return state


def hash_value(s):
    return hashlib.sha256(str(s).encode("utf-8")).hexdigest()


def escape(s):
    return html.escape(str(s), quote=True)


def coordinate(value, north_east, south_west):
    direction = north_east if float(value) >= 0 else south_west
    number = f"{abs(float(value)):.2f}".replace(".", ",")
    return f"{number}° {direction}"


def slugify(value):
    """Human-readable ASCII slug; always bounded and safe for WordPress."""
    ascii_text = unicodedata.normalize("NFKD", str(value))
    ascii_text = ascii_text.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def readable_region(value):
    """Avoid markup in SEO metadata while preserving the actual BMKG location."""
    plain = html.unescape(re.sub(r"<[^>]*>", " ", str(value)))
    return " ".join(plain.split())


def seo_title(e, date):
    mag = magnitude(e["magnitude"])
    region = readable_region(e["region"])
    full = f"Gempa M{mag} di {region}, {date} - BMKG"
    if len(full) <= 75:
        return full
    concise = f"Gempa M{mag} di {region}, {date}"
    if len(concise) <= 78:
        return concise
    # Prefer a complete word in a shortened headline, not a misleading new place.
    left, right = f"Gempa M{mag} di ", f", {date}"
    limit = max(12, 78 - len(left) - len(right) - 1)
    short = region[:limit].rsplit(" ", 1)[0] or region[:limit]
    return left + short.rstrip(" ,") + "…" + right


def seo_slug(e, date_iso):
    region = slugify(readable_region(e["region"]))
    # Full source region is kept in the title/body; the URL keeps its main keywords.
    region = "-".join(region.split("-")[:6])[:42].rstrip("-") or "episentrum"
    # Stable occurrence suffix prevents collisions for multiple earthquakes.
    return f"gempa-{region}-{date_iso}-{e['key'][:8]}"


def seo_excerpt(e, date, time, depth):
    mag = magnitude(e["magnitude"])
    region = readable_region(e["region"])
    prefix = f"Gempa M{mag} di {region} pada {date}, pukul {time} WIB. "
    middle = f"Kedalaman {depth} km. "
    ending = ("BMKG: tidak berpotensi tsunami." if confirmed_no_tsunami(e)
              else "Simak informasi resmi BMKG.")
    summary = prefix + middle + ending
    if len(summary) <= 160:
        return summary
    # Preserve the factual tsunami wording by reducing the location, not the claim.
    fixed = f"Gempa M{mag} di " + f" pada {date}. " + middle + ending
    budget = 160 - len(fixed) - 1
    if budget > 15:
        short = region[:budget].rsplit(" ", 1)[0] or region[:budget]
        return f"Gempa M{mag} di {short.rstrip(' ,')}… pada {date}. " + middle + ending
    return f"Gempa M{mag} pada {date}. " + middle + ending


def editorial_tags(e):
    """Curated single-word tags; no unbounded taxonomy from BMKG free text."""
    names = ["Gempa", "BMKG", "Episentrum", "Seismik"]
    location = readable_region(e["region"]).casefold()
    mapping = (
        ("jawa", "Jawa"), ("java", "Jawa"), ("sumatera", "Sumatera"),
        ("sumatra", "Sumatera"), ("sulawesi", "Sulawesi"),
        ("kalimantan", "Kalimantan"), ("borneo", "Kalimantan"),
        ("papua", "Papua"), ("maluku", "Maluku"), ("bali", "Bali"),
        ("aceh", "Aceh"), ("lombok", "Lombok"), ("flores", "Flores"),
        ("banda", "Banda"), ("sumbawa", "Sumbawa"),
        ("halmahera", "Halmahera"), ("ambon", "Ambon"),
        ("seram", "Seram"), ("timor", "Timor"),
    )
    for token, tag in mapping:
        if re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", location):
            if tag not in names:
                names.append(tag)
            break
    return names[:8]


def article(e):
    local = timestamp(e["datetime"]).astimezone(WIB)
    days = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
    months = ("Januari", "Februari", "Maret", "April", "Mei", "Juni",
              "Juli", "Agustus", "September", "Oktober", "November", "Desember")
    date = f"{local.day} {months[local.month - 1]} {local.year}"
    day = days[local.weekday()]
    time = local.strftime("%H.%M")
    mag = magnitude(e["magnitude"])
    depth = f"{e['depth_km']:g}".replace(".", ",")
    region = escape(e["region"])

    # Exactly four editorial paragraphs; never infer damage, casualties or shaking intensity.
    paragraphs = [
        (f"Gempa M{mag} di {region} terjadi pada {day}, {date}, pukul "
         f"{time} WIB, menurut Badan Meteorologi, Klimatologi, dan Geofisika "
         f"(BMKG). Informasi kejadian tersebut dipublikasikan melalui data "
         f"gempa resmi BMKG."),
        (f"Menurut parameter BMKG, koordinat episentrum berada di "
         f"{escape(coordinate(e['lat'], 'LU', 'LS'))} dan "
         f"{escape(coordinate(e['lon'], 'BT', 'BB'))}. "
         f"Pusat gempa dilaporkan berada pada kedalaman {depth} kilometer."),
    ]
    potential = str(e.get("potential") or "").strip()
    felt = str(e.get("felt_info") or "").strip()
    p3a = (f"BMKG menyampaikan keterangan mengenai potensi tsunami: "
           f"{escape(potential.rstrip('.'))}." if potential else
           "Keterangan potensi tsunami belum tercantum dalam data BMKG yang digunakan.")
    p3b = (f"BMKG juga menyertakan informasi guncangan yang dirasakan: "
           f"{escape(felt.rstrip('.'))}." if felt else
           "Rincian wilayah yang merasakan guncangan belum tercantum dalam data yang digunakan.")
    paragraphs.append(p3a + " " + p3b)

    sources = sorted({BASE + name for name in e["sources"]})
    links = ", ".join(f'<a href="{escape(url)}">data BMKG</a>' for url in sources)
    paragraphs.append(
        f"Informasi magnitudo, waktu, koordinat, dan kedalaman dalam artikel "
        f"ini bersumber dari {links}. Parameter kejadian dapat berubah "
        f"apabila BMKG merilis pembaruan. (RK/D-1)"
    )
    body = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
    # Hidden provenance marker is adjacent to the final closing tag, with no newline.
    body += f"<!-- {MARKER}{e['key']} -->"
    yoast_meta = {
        "_yoast_wpseo_focuskw": f"gempa M{mag} di {readable_region(e['region'])}",
        "_yoast_wpseo_title": seo_title(e, date),
        "_yoast_wpseo_metadesc": seo_excerpt(e, date, time, depth),
    }
    return {
        "title": escape(seo_title(e, date)),
        "content": body,
        "excerpt": escape(seo_excerpt(e, date, time, depth)),
        "slug": seo_slug(e, local.strftime("%Y-%m-%d")),
        "tag_names": editorial_tags(e),
        "yoast_meta": yoast_meta,
        "comment_status": "closed",
    }


def daily_article(records, day):
    selected = [r["data"] for r in records
                if 5.0 <= r["data"]["magnitude"] < 5.5 and
                timestamp(r["data"]["datetime"]).astimezone(WIB).date() == day]
    if not selected:
        return None
    selected.sort(key=lambda e: e["datetime"])
    rows = []
    for e in selected:
        when = timestamp(e["datetime"]).astimezone(WIB).strftime("%H.%M")
        depth = format(e["depth_km"], "g")
        rows.append(f"<tr><td>{escape(when)} WIB</td><td>{escape(magnitude(e['magnitude']))}"
                    f"</td><td>{escape(e['region'])}</td><td>{escape(depth)} km</td></tr>")
    readable_day = f"{day.day} {('Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember')[day.month - 1]} {day.year}"
    title = f"Daftar Gempa M5,0–5,4 pada {readable_day} Menurut BMKG"
    paragraphs = [
        (f"Berdasarkan kejadian yang berhasil dipantau Dataloka dari BMKG, "
         f"terdapat {len(selected)} gempa bermagnitudo 5,0 hingga kurang dari "
         f"5,5 pada {day:%d-%m-%Y}. Angka tersebut bukan total resmi seluruh gempa "
         f"pada tanggal itu."),
        ("Rincian kejadian yang terpantau ditampilkan dalam tabel berikut. "
         "Waktu kejadian telah dinyatakan dalam Waktu Indonesia Barat (WIB)."),
        ('Data diperoleh dari <a href="https://data.bmkg.go.id/gempabumi/">BMKG</a>. '
         "Rangkuman menggunakan kejadian yang tersimpan dalam pemantauan Dataloka, "
         "sehingga cakupannya dapat berbeda dari rekap lengkap instansi."),
        ("Ringkasan ini bersifat pendahuluan dan memerlukan pemeriksaan redaksi "
         "sebelum diterbitkan. Parameter kejadian dapat berubah apabila BMKG "
         "memperbarui data. (RK/D-1)"),
    ]
    table = ("<table><thead><tr><th>Waktu</th><th>Magnitudo</th><th>Wilayah</th>"
             "<th>Kedalaman</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    body = "<p>" + paragraphs[0] + "</p><p>" + paragraphs[1] + "</p>" + table
    body += "<p>" + paragraphs[2] + "</p><p>" + paragraphs[3] + "</p>"
    body += f"<!-- dataloka-bmkg-daily:{day.isoformat()} -->"
    description = (f"Daftar gempa M5,0–5,4 pada {readable_day} berdasarkan data "
                   f"BMKG yang dipantau Dataloka. Lihat waktu, wilayah, dan kedalaman.")
    return {"title": title, "content": body,
            "excerpt": description,
            "slug": f"daftar-gempa-m50-m54-{day.isoformat()}",
            "tag_names": ["Gempa", "BMKG", "Seismik"],
            "yoast_meta": {
                "_yoast_wpseo_focuskw": f"gempa M5,0–5,4 {readable_day}",
                "_yoast_wpseo_title": title,
                "_yoast_wpseo_metadesc": description,
            },
            "comment_status": "closed"}


class EditorialConflict(RuntimeError):
    """Human-owned WordPress changes: never overwrite, skip only this event."""


class WordPress:
    def __init__(self, user, password):
        if not user or not password:
            raise ValueError("Missing Dataloka WordPress secrets")
        self.authorization = "Basic " + base64.b64encode(
            f"{user}:{password}".encode("utf-8")).decode("ascii")
        self._tag_cache = {}
        self._berita_id = None

    def call(self, method, route, params=None, payload=None):
        url = WP_URL + "/wp-json/wp/v2/" + route
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None if payload is None else json.dumps(
            payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": self.authorization,
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Dataloka-BMKG/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.loads(response.read(1_000_000).decode("utf-8"))
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"WordPress returned HTTP {err.code} on {method} {route}") from None

    def cover_image(self, event):
        """Reuse a stable upload when a retry occurs after WordPress accepted media."""
        from scripts.dataloka_gempa_image import render

        media_slug = "bmkg-gempa-" + event["key"] + "-peta"
        matching = self.call("GET", "media", {
            "slug": media_slug, "context": "edit", "per_page": 2,
        })
        if matching:
            return int(matching[0]["id"])

        jpg = render(event)
        filename = media_slug + ".jpg"
        req = urllib.request.Request(
            WP_URL + "/wp-json/wp/v2/media",
            data=jpg,
            method="POST",
            headers={
                "Authorization": self.authorization,
                "Accept": "application/json",
                "Content-Type": "image/jpeg",
                "Content-Disposition": 'attachment; filename="' + filename + '"',
                "User-Agent": "Dataloka-BMKG/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=40) as response:
                created = json.loads(response.read(1_000_000).decode("utf-8"))
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"WordPress refused cover image upload: HTTP {err.code}") from None

        media_id = int(created["id"])
        mag = magnitude(event["magnitude"])
        description = f"Peta episentrum gempa M{mag} di {event['region']} berdasarkan koordinat BMKG"
        self.call("POST", "media/" + str(media_id), payload={
            "alt_text": description,
            "title": description,
            "caption": "Peta lokasi episentrum berdasarkan data BMKG. Geografi: Natural Earth.",
        })
        return media_id

    def berita_category_id(self):
        """Find the existing WordPress category named Berita; never assume an ID."""
        if self._berita_id is not None:
            return self._berita_id
        terms = self.call("GET", "categories", {
            "search": "Berita", "per_page": 100,
        })
        exact = [
            term for term in terms if
            html.unescape(str(term.get("name", ""))).strip().casefold() == "berita"
            or str(term.get("slug", "")).strip().casefold() == "berita"
        ]
        if not exact:
            raise RuntimeError(
                "Kategori 'Berita' tidak ditemukan di WordPress Dataloka; "
                "artikel bot tidak dikirim agar tidak salah kategori."
            )
        selected = next(
            (term for term in exact if term.get("slug") == "berita"),
            exact[0],
        )
        self._berita_id = int(selected["id"])
        return self._berita_id

    def resolve_tags(self, names):
        """Resolve existing WP term IDs, create missing terms if role permits.

        A missing ability to create tags must not delay a time-sensitive earthquake
        publication. Unresolved tags are reported in Actions logs for editorial review.
        """
        term_ids = []
        for name in list(dict.fromkeys(names))[:8]:
            if not name or " " in name:
                continue
            if name in self._tag_cache:
                term_id = self._tag_cache[name]
            else:
                try:
                    matches = self.call("GET", "tags", {
                        "search": name, "per_page": 100,
                    })
                    exact = next(
                        (tag for tag in matches if
                         html.unescape(str(tag.get("name", ""))).casefold() == name.casefold()),
                        None)
                    if exact:
                        term_id = int(exact["id"])
                    else:
                        created = self.call("POST", "tags", payload={
                            "name": name, "slug": slugify(name),
                        })
                        term_id = int(created["id"])
                except (RuntimeError, KeyError, ValueError, TypeError) as exc:
                    # Permission 403 on /tags creation is common for Author roles.
                    print(f"WARNING: WordPress tag '{name}' unavailable: {exc}",
                          file=sys.stderr)
                    term_id = 0
                self._tag_cache[name] = term_id
            if term_id and term_id not in term_ids:
                term_ids.append(term_id)
        return term_ids

    def by_slug(self, slug):
        posts = self.call("GET", "posts", {
            "slug": slug, "status": "any", "context": "edit", "per_page": 2})
        return posts[0] if posts else None

    def by_id(self, post_id):
        return self.call("GET", "posts/" + str(int(post_id)), {"context": "edit"})

    @staticmethod
    def _verified_yoast(post, desired):
        """Require exact persistence; WordPress can silently ignore unregistered meta."""
        meta = post.get("meta")
        if not isinstance(meta, dict) or any(k not in meta for k in YOAST_KEYS):
            raise RuntimeError(
                "Yoast metadata belum tersedia pada REST API WordPress. "
                "Aktifkan dukungan meta REST (Yoast terbaru atau plugin bridge); "
                "artikel baru tetap berstatus draf, tidak terbit tanpa SEO."
            )
        actual = {key: str(meta[key]) for key in YOAST_KEYS}
        if any(actual[key] != desired[key] for key in YOAST_KEYS):
            raise RuntimeError(
                "WordPress tidak menyimpan seluruh Yoast SEO metadata sesuai permintaan. "
                "Periksa dukungan REST Yoast dan hak akses akun bot; "
                "publikasi artikel baru ditahan sebagai draf."
            )
        return actual

    def save(self, payload, ledger, status, marker, event=None):
        desired_yoast = payload.get("yoast_meta", {})
        if set(desired_yoast) != set(YOAST_KEYS):
            raise ValueError("Yoast field set incomplete; refusing unsafe publication")
        found = (self.by_id(ledger["post_id"]) if ledger.get("post_id")
                 else self.by_slug(payload["slug"]))
        if found:
            raw = found.get("content", {}).get("raw", "")
            if marker not in raw:
                raise EditorialConflict(f"Post {found['id']} has no Dataloka ownership marker")
            previous_digest = ledger.get("last_wp_digest")
            if not previous_digest:
                if (hash_value(raw) != hash_value(payload["content"]) or
                    found.get("status") not in (status, "draft")):
                    raise EditorialConflict(
                        "Existing untracked WordPress post differs from bot payload; "
                        "manual reconciliation required"
                    )
                previous_digest = hash_value(raw)
            if hash_value(raw) != previous_digest:
                raise EditorialConflict(f"Post {found['id']} edited manually; refusing overwrite")
            if found.get("status") == "publish" and status != "publish":
                raise EditorialConflict(f"Cannot downgrade published post {found['id']}")

            prior_media = ledger.get("media_id")
            current_media = int(found.get("featured_media") or 0)
            if prior_media and current_media not in (0, int(prior_media)):
                raise EditorialConflict(f"Featured image on post {found['id']} edited manually")

            # Check that old SEO metadata is readable before modifying existing posts.
            existing_meta = found.get("meta")
            if not isinstance(existing_meta, dict) or any(
                key not in existing_meta for key in YOAST_KEYS
            ):
                raise RuntimeError(
                    "Yoast REST meta keys are not exposed; existing post unchanged"
                )
            before = {key: str(existing_meta[key]) for key in YOAST_KEYS}
            previous_yoast_digest = ledger.get("yoast_meta_digest")
            if previous_yoast_digest:
                if hash_value(json.dumps(before, sort_keys=True, ensure_ascii=False)) != previous_yoast_digest:
                    raise EditorialConflict(
                        f"Yoast SEO fields on post {found['id']} edited manually; refusing overwrite"
                    )
            elif any(before[key] and before[key] != desired_yoast[key]
                     for key in YOAST_KEYS):
                raise EditorialConflict(
                    f"Existing Yoast SEO fields on post {found['id']} differ; "
                    "refusing overwrite without editor reconciliation"
                )

            new_payload = dict(payload)
            new_payload.pop("slug", None)  # Never rewrite existing public permalinks.
            tag_names = new_payload.pop("tag_names", [])
            new_payload["meta"] = new_payload.pop("yoast_meta")
            new_payload["status"] = status
            new_payload["categories"] = [self.berita_category_id()]
            if tag_names and not found.get("tags"):
                term_ids = self.resolve_tags(tag_names)
                if term_ids:
                    new_payload["tags"] = term_ids
            if status == "publish" and event and not current_media:
                new_payload["featured_media"] = self.cover_image(event)

            post = self.call("POST", "posts/" + str(found["id"]), payload=new_payload)
            confirmed = self.by_id(post["id"])
            self._verified_yoast(confirmed, desired_yoast)
        else:
            new_payload = dict(payload)
            tag_names = new_payload.pop("tag_names", [])
            new_payload["meta"] = new_payload.pop("yoast_meta")
            # Publish only AFTER verifying the requested Yoast fields on the draft.
            new_payload["status"] = "draft"
            if tag_names:
                term_ids = self.resolve_tags(tag_names)
                if term_ids:
                    new_payload["tags"] = term_ids
            new_payload["categories"] = [self.berita_category_id()]
            if status == "publish" and event:
                new_payload["featured_media"] = self.cover_image(event)
            post = self.call("POST", "posts", payload=new_payload)
            confirmed = self.by_id(post["id"])
            self._verified_yoast(confirmed, desired_yoast)
            if confirmed.get("slug") != payload["slug"]:
                raise RuntimeError(
                    f"WordPress changed the requested SEO slug for draft {post['id']}; "
                    "new article is not being published"
                )
            if status == "publish":
                post = self.call("POST", "posts/" + str(post["id"]), payload={
                    "status": "publish",
                })
                confirmed = self.by_id(post["id"])
                self._verified_yoast(confirmed, desired_yoast)

        if marker not in confirmed.get("content", {}).get("raw", ""):
            raise RuntimeError(f"WordPress stripped ownership marker for post {post['id']}")
        if confirmed.get("status") != status:
            raise RuntimeError(
                f"WordPress returned status {confirmed.get('status')} instead of {status}"
            )
        if status == "publish" and event and not int(confirmed.get("featured_media") or 0):
            raise RuntimeError(f"Published post {post['id']} has no featured media")
        return self._mapping(confirmed, payload)

    @staticmethod
    def _mapping(post, payload):
        actual_meta = {key: str(post["meta"][key]) for key in YOAST_KEYS}
        return {
            "post_id": post["id"],
            "media_id": int(post.get("featured_media") or 0),
            "last_wp_digest": hash_value(post.get("content", {}).get("raw", "")),
            "yoast_meta_digest": hash_value(json.dumps(
                actual_meta, ensure_ascii=False, sort_keys=True)),
            "status": post["status"],
            "last_payload_digest": hash_value(json.dumps(
                payload, ensure_ascii=False, sort_keys=True)),
        }


def events_task(mode, wp, now):
    events = get_events()
    state = read_state()
    for event in events:
        age = (now - timestamp(event["datetime"])).total_seconds() / 60
        if age < -5 or age > 14 * 1440:
            continue
        record = next((r for r in state["events"] if same_event(r["data"], event)), None)
        if record is None:
            record = {"key": event["key"], "data": event}
            state["events"].append(record)
        else:
            updated = merge(record["data"], event)
            # A missing tsunami status must never inherit a previous clearance.
            updated["potential"] = event.get("potential", "")
            updated["key"] = record["key"]
            record["data"] = updated
        event = record["data"]
        if not (event["magnitude"] >= 5 or event["felt"]):
            continue
        if not record.get("post_id") and age > 120:
            continue
        status = status_for(event, mode)
        # A corrected magnitude does not automatically unpublish an existing
        # article; update its facts in place while retaining the public URL.
        if record.get("status") == "publish":
            status = "publish"
        payload = article(event)
        payload_digest = hash_value(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        if (record.get("last_payload_digest") == payload_digest and
                record.get("status") == status and
                (status != "publish" or record.get("media_id"))):
            continue
        print(f"{mode}: {status} M{event['magnitude']:.1f} {event['region']}")
        if mode != "dry-run":
            try:
                record.update(wp.save(
                    payload, record, status, f"<!-- {MARKER}{record['key']} -->", event=event))
            except EditorialConflict as exc:
                # A human-edited draft must not block all other earthquakes.
                print(f"SKIP editorial conflict on event {record['key']}: {exc}", file=sys.stderr)
    if mode != "dry-run":
        state["events"] = [
            x for x in state["events"] if x.get("post_id") or
            (now - timestamp(x["data"]["datetime"])).days < 15]
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Processed {len(events)} official BMKG entries; mode={mode}")


def daily_task(mode, wp, now):
    state = read_state()
    day = now.astimezone(WIB).date() - dt.timedelta(days=1)
    payload = daily_article(state["events"], day)
    if not payload:
        print(f"No monitored M5.0-5.4 earthquakes on {day}")
        return
    print(f"{mode}: daily draft {day}")
    if mode == "dry-run":
        return
    old = state.setdefault("daily", {}).get(day.isoformat(), {})
    try:
        result = wp.save(payload, old, "draft",
                         f"<!-- dataloka-bmkg-daily:{day.isoformat()} -->")
    except EditorialConflict as exc:
        print(f"SKIP daily editorial conflict {day}: {exc}", file=sys.stderr)
        return
    state["daily"][day.isoformat()] = result
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("live", "drafts", "dry-run"), default="dry-run")
    parser.add_argument("--task", choices=("events", "daily"), default="events")
    args = parser.parse_args()
    wp = None if args.mode == "dry-run" else WordPress(
        os.getenv("WP_USERNAME"), os.getenv("WP_APP_PASSWORD"))
    now = dt.datetime.now(UTC)
    if args.task == "events":
        events_task(args.mode, wp, now)
    else:
        daily_task(args.mode, wp, now)


if __name__ == "__main__":
    main()
