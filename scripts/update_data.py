#!/usr/bin/env python3
"""Fetch and normalize BMKG open earthquake API feeds (stdlib only).

This script targets the documented public JSON API, not website scraping.
For commercial/repackaged display, obtain the required written permission
before activating the scheduled workflow.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://data.bmkg.go.id/DataMKG/TEWS/"
FEEDS = {"latest": "autogempa.json", "m5": "gempaterkini.json", "felt": "gempadirasakan.json"}
MAX_EVENTS = 1200
ROOT = pathlib.Path(__file__).resolve().parents[1]
FILE = ROOT / "data" / "gempa.json"


def numeric(value, label):
    try:
        result = float(str(value).replace(',', '.'))
        if not math.isfinite(result):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise ValueError(f"Invalid {label}: {value!r}")


def parse_event(raw, feed):
    """Validate and normalize one BMKG event; no content is fabricated."""
    if not isinstance(raw, dict):
        raise ValueError("not an event object")
    instant = dt.datetime.fromisoformat(str(raw['DateTime']).replace('Z', '+00:00'))
    if instant.tzinfo is None:
        raise ValueError("DateTime must include timezone")
    instant = instant.astimezone(dt.timezone.utc)
    if instant.year < 2000 or instant > dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1):
        raise ValueError("DateTime outside expected range")
    coords = str(raw['Coordinates']).split(',')
    if len(coords) != 2:
        raise ValueError("Coordinates must be lat,lon")
    lat, lon = (numeric(x.strip(), 'coordinate') for x in coords)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"Invalid geographic coordinates: {lat},{lon}")
    magnitude = numeric(raw['Magnitude'], 'magnitude')
    if not 0 <= magnitude <= 10:
        raise ValueError("Magnitude out of range")
    match = re.search(r'([\d.,]+)', str(raw['Kedalaman']))
    if not match:
        raise ValueError("Depth missing")
    depth = numeric(match.group(1), 'depth')
    if not 0 <= depth <= 900:
        raise ValueError("Depth out of range")
    region = str(raw.get('Wilayah') or '').strip()
    if not region:
        raise ValueError('Region missing')
    felt_info = str(raw.get('Dirasakan') or '').strip()
    potential_raw = str(raw.get('Potensi') or '').strip()
    low = potential_raw.lower()
    tsunami = ('berpotensi tsunami' in low and not ('tidak berpotensi tsunami' in low or 'tak berpotensi tsunami' in low))
    felt = bool(felt_info) or feed == 'felt'
    is_m5 = magnitude >= 5
    significant = magnitude >= 6 or tsunami
    if not (is_m5 or felt or significant):
        return None
    canonical = f"{instant.strftime('%Y%m%dT%H%M%S')}:{lat:.2f}:{lon:.2f}"
    event_id = hashlib.sha1(canonical.encode()).hexdigest()[:14]
    return {
        'id': event_id,
        'datetime': instant.isoformat().replace('+00:00','Z'),
        'magnitude': magnitude,
        'depth_km': depth,
        'lat': lat,
        'lon': lon,
        'region': region,
        'felt': felt,
        'felt_info': felt_info,
        'tsunami': tsunami,
        'potential_text': potential_raw,
        'significant': significant,
        'source_types': [feed],
        'source_urls': [BASE + FEEDS[feed]],
        'shakemap': str(raw.get('Shakemap') or '').strip(),
    }


def distance_km(a, b):
    r = math.pi / 180
    x = (a['lon'] - b['lon']) * math.cos((a['lat'] + b['lat']) / 2 * r)
    y = a['lat'] - b['lat']
    return 111.2 * math.hypot(x, y)


def same_event(a, b):
    """Time and location tolerance across feeds; not a government event ID."""
    seconds = abs((dt.datetime.fromisoformat(a['datetime'].replace('Z','+00:00')) -
                  dt.datetime.fromisoformat(b['datetime'].replace('Z','+00:00'))).total_seconds())
    if seconds <= 2 and distance_km(a,b) <= 50:
        return True
    return (seconds <= 45 and distance_km(a,b) <= 10 and
            abs(a['magnitude'] - b['magnitude']) <= 0.3)


def merge(old, new):
    out = dict(old)
    out['source_types'] = sorted(set(old.get('source_types',[])) | set(new.get('source_types',[])))
    out['source_urls'] = sorted(set(old.get('source_urls',[])) | set(new.get('source_urls',[])))
    out['felt'] = bool(old.get('felt') or new.get('felt'))
    out['tsunami'] = bool(old.get('tsunami'))
    # Explicit tsunami revisions replace old status (including cancellation).
    if 'tsunami' in str(new.get('potential_text') or '').lower():
        out['tsunami'] = bool(new.get('tsunami'))
    # Prefer version with more complete felt details; do not erase values with blanks.
    for field in ['felt_info', 'shakemap']:
        if len(str(new.get(field) or '')) > len(str(old.get(field) or '')):
            out[field] = new[field]
    if new.get('potential_text') and ('tsunami' in new['potential_text'].lower() or not old.get('potential_text')):
        out['potential_text'] = new['potential_text']
    # Apply newer agency metadata while retaining the stable internal event ID.
    # BMKG feeds do not expose a unique immutable earthquake identifier.
    for field in ['magnitude', 'depth_km', 'lat', 'lon', 'datetime']:
        out[field] = new[field]
    if len(new.get('region') or '') > len(old.get('region') or ''):
        out['region'] = new['region']
    out['significant'] = out['magnitude'] >= 6 or out['tsunami']
    return out


def fetch_feed(feed_name, fixture_dir=None):
    if fixture_dir:
        with open(pathlib.Path(fixture_dir) / FEEDS[feed_name], encoding='utf-8') as fh:
            return json.load(fh)
    url = BASE + FEEDS[feed_name]
    req = urllib.request.Request(url, headers={
        'User-Agent': 'DatalokaGempaMonitor/1.0 (BMKG open JSON API; attributed)',
        'Accept':'application/json', 'Cache-Control':'no-cache'
    })
    for trial in range(3):
        try:
            with urllib.request.urlopen(req, timeout=18) as response:
                if response.status != 200:
                    raise ValueError(f'HTTP {response.status}')
                content = response.read(300000)
                return json.loads(content.decode('utf-8-sig'))
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            if trial == 2:
                raise RuntimeError(f'BMKG {feed_name} failed: {exc}') from exc
            time.sleep(2 ** trial)


def ingest(existing, feeds, now):
    saved = [dict(x) for x in existing if isinstance(x, dict) and x.get('id')]
    issues = []
    for feed, doc in feeds.items():
        raw_events = doc.get('Infogempa', {}).get('gempa')
        if isinstance(raw_events, dict):
            raw_events = [raw_events]
        if not isinstance(raw_events, list) or not raw_events:
            raise ValueError(f'Unexpected or empty BMKG {feed} response')
        valid = 0
        for raw in raw_events:
            try:
                evt = parse_event(raw, feed)
            except (ValueError, KeyError) as exc:
                issues.append(f'{feed}: {str(exc)[:150]}')
                continue
            if evt is None:
                continue
            valid += 1
            match = next((i for i,x in enumerate(saved) if same_event(x,evt)), None)
            if match is None:
                evt['first_seen_at'] = now
                evt['last_updated_at'] = now
                saved.append(evt)
            else:
                updated = merge(saved[match], evt)
                updated['first_seen_at'] = saved[match].get('first_seen_at', now)
                updated['last_updated_at'] = saved[match].get('last_updated_at', now)
                if {k:v for k,v in updated.items() if k != 'last_updated_at'} != {k:v for k,v in saved[match].items() if k != 'last_updated_at'}:
                    updated['last_updated_at'] = now
                saved[match] = updated
        if valid == 0 and feed != 'latest':
            raise ValueError(f'No valid events in {feed}; refusing to overwrite data')
    saved.sort(key=lambda x: x['datetime'], reverse=True)
    return saved[:MAX_EVENTS], issues


def main():
    cli = argparse.ArgumentParser(description='Update Dataloka BMKG earthquake monitor')
    cli.add_argument('--fixtures-dir', default=None, help='Only for offline testing; do not publish fixture output as live')
    cli.add_argument('--output', default=str(FILE))
    args = cli.parse_args()
    dest = pathlib.Path(args.output)
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')
    old = {}
    if dest.exists():
        old = json.loads(dest.read_text(encoding='utf-8'))
    feeds = {name:fetch_feed(name,args.fixtures_dir) for name in FEEDS}
    # A curated preview is not a historical archive. Start a clean live collection.
    previous = old.get('events', []) if old.get('status') == 'live' else []
    events, errors = ingest(previous, feeds, now)
    payload = {
        'schema_version': 1,
        'status': 'fixture' if args.fixtures_dir else 'live',
        'checked_at': now,
        'source': 'Badan Meteorologi, Klimatologi, dan Geofisika (BMKG)',
        'coverage_note': 'Arsip lokal dari tiga feed BMKG (masing-masing dibatasi hingga 15 kejadian); bukan sensus seluruh gempa Indonesia.',
        'sources': {k: BASE+v for k,v in FEEDS.items()},
        'errors': errors[:20],
        'events': events,
    }
    # Every scheduled run checks the API, but unchanged data is published hourly
    # to avoid 96 redundant git commits per day. New events publish at once.
    if old.get('status') == 'live' and old.get('events') == events and old.get('errors') == payload['errors']:
        previous_check = dt.datetime.fromisoformat(old['checked_at'].replace('Z','+00:00')) if old.get('checked_at') else None
        if previous_check and dt.datetime.now(dt.timezone.utc) - previous_check < dt.timedelta(minutes=60):
            print('No event changes; keeping last published JSON (hourly heartbeat).')
            return
    # Atomic replacement prevents a failed pull from corrupting current data.
    dest.parent.mkdir(parents=True,exist_ok=True)
    temp = dest.with_suffix('.tmp')
    temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2), encoding='utf-8')
    temp.replace(dest)
    print(f'[{now}] merged {len(events)} unique events; {len(errors)} invalid records; {payload["status"]}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'UPDATE FAILED (existing file preserved): {exc}', file=sys.stderr)
        raise SystemExit(1)
