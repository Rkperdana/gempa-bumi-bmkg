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
from html.parser import HTMLParser

BASE = "https://data.bmkg.go.id/DataMKG/TEWS/"
FEEDS = {"latest": "autogempa.json", "m5": "gempaterkini.json", "felt": "gempadirasakan.json"}
MAX_EVENTS = 1200
REALTIME_URL = 'https://www.bmkg.go.id/gempabumi/gempabumi-realtime'
WIB = dt.timezone(dt.timedelta(hours=7))
MONTHS = {'jan':1,'feb':2,'mar':3,'apr':4,'mei':5,'may':5,'jun':6,'jul':7,'agu':8,'ags':8,'aug':8,'sep':9,'okt':10,'oct':10,'nov':11,'des':12,'dec':12}
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



class RealtimeTableParser(HTMLParser):
    """Extract SSR table rows from the official 200-earthquake HTML page."""
    def __init__(self):
        super().__init__()
        self.rows = []
        self.table_depth = 0
        self.in_row = False
        self.in_cell = False
        self.cells = []
        self.fragments = []

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.table_depth += 1
        if self.table_depth and tag == 'tr':
            self.in_row = True
            self.cells = []
        if self.in_row and tag in ('td', 'th'):
            self.in_cell = True
            self.fragments = []

    def handle_data(self, data):
        if self.in_cell:
            self.fragments.append(data)

    def handle_endtag(self, tag):
        if self.in_cell and tag in ('td', 'th'):
            self.cells.append(' '.join(' '.join(self.fragments).split()))
            self.in_cell = False
        if self.in_row and tag == 'tr':
            if self.cells:
                self.rows.append(self.cells)
            self.in_row = False
        if tag == 'table':
            self.table_depth = max(self.table_depth - 1, 0)


def parse_realtime_row(cells):
    """Parse BMKG's real-time table; convert WIB to UTC and hemispheres to signed degrees."""
    if len(cells) < 6 or not cells[0].strip().isdigit():
        return None
    match = re.fullmatch(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s+(\d{2})[.:](\d{2})[.:](\d{2})\s+WIB', cells[1], re.I)
    if not match:
        raise ValueError('Invalid WIB timestamp: ' + repr(cells[1]))
    day, month, year, hour, minute, second = match.groups()
    month_num = MONTHS.get(month.lower())
    if not month_num:
        raise ValueError('Unknown month: ' + month)
    instant = dt.datetime(int(year), month_num, int(day), int(hour), int(minute), int(second), tzinfo=WIB).astimezone(dt.timezone.utc)
    magnitude = numeric(cells[2], 'magnitude')
    if not 0 <= magnitude <= 10:
        raise ValueError('Magnitude out of range')
    depth_match = re.search(r'(\d+(?:[.,]\d+)?)', cells[3])
    if not depth_match:
        raise ValueError('Depth missing')
    depth = numeric(depth_match.group(1), 'depth')
    if not 0 <= depth <= 900:
        raise ValueError('Depth out of range')
    coords = re.search(r'(\d+(?:[.,]\d+)?)\s*(LU|LS)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*(BT|BB)', cells[4], re.I)
    if not coords:
        raise ValueError('Invalid coordinates: ' + repr(cells[4]))
    lat = numeric(coords.group(1), 'latitude') * (-1 if coords.group(2).upper() == 'LS' else 1)
    lon = numeric(coords.group(3), 'longitude') * (-1 if coords.group(4).upper() == 'BB' else 1)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Coordinates out of range')
    region = cells[5].strip()
    if not region:
        raise ValueError('Missing F-E region')
    event_id = hashlib.sha1(f"{instant.strftime('%Y%m%dT%H%M%S')}:{lat:.2f}:{lon:.2f}".encode()).hexdigest()[:14]
    return {
        'id': event_id, 'datetime': instant.isoformat().replace('+00:00', 'Z'),
        'magnitude': magnitude, 'depth_km': depth, 'lat': lat, 'lon': lon,
        'region': region, 'felt': False, 'felt_info': '', 'tsunami': False,
        'potential_text': '', 'significant': magnitude >= 6,
        'source_types': ['realtime'], 'source_urls': [REALTIME_URL],
        'shakemap': '',
    }


def parse_realtime_html(html):
    parser = RealtimeTableParser()
    parser.feed(html)
    events = []
    errors = []
    seen = set()
    for cells in parser.rows:
        if len(cells) < 6 or not cells[0].strip().isdigit():
            continue
        try:
            event = parse_realtime_row(cells)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if event and event['id'] not in seen:
            events.append(event)
            seen.add(event['id'])
    # Fail closed if the BMKG page markup changed or loaded only partial content.
    if len(events) < 100 or len(errors) > 10:
        raise ValueError(f'Realtime HTML extraction incomplete: {len(events)} events, {len(errors)} invalid rows')
    events.sort(key=lambda x: x['datetime'], reverse=True)
    return events[:200]


def fetch_realtime_html():
    request = urllib.request.Request(REALTIME_URL, headers={
        'User-Agent':'Mozilla/5.0 (compatible; DatalokaGempaMonitor/1.1; attributed BMKG)',
        'Accept':'text/html', 'Cache-Control':'no-cache'
    })
    for trial in range(3):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                if response.status != 200:
                    raise ValueError(f'HTTP {response.status}')
                html = response.read(2000000).decode('utf-8-sig', 'replace')
                if 'Gempa Bumi Real-time' not in html:
                    raise ValueError('Expected BMKG realtime heading not found')
                return html
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            if trial == 2:
                raise RuntimeError(f'BMKG realtime page failed: {exc}') from exc
            time.sleep(2 ** trial)


def enrich_realtime(events, feeds, previous, now):
    """Use supplemental JSON only for M5/felt/tsunami labels; never replace real-time parameters."""
    warnings = []
    for event in events:
        previous_event = next((p for p in previous if p.get('id') == event['id']), None)
        event['first_seen_at'] = previous_event.get('first_seen_at', now) if previous_event else now
        event['last_updated_at'] = now
    for feed, document in feeds.items():
        raw_events = document.get('Infogempa', {}).get('gempa')
        if isinstance(raw_events, dict):
            raw_events = [raw_events]
        if not isinstance(raw_events, list):
            warnings.append(f'{feed}: unexpected format')
            continue
        for raw in raw_events:
            try:
                item = parse_event(raw, feed)
            except (ValueError, KeyError) as exc:
                warnings.append(f'{feed}: {str(exc)[:120]}')
                continue
            if not item:
                continue
            match = next((event for event in events if same_event(event, item)), None)
            if not match:
                continue
            match['source_types'] = sorted(set(match['source_types'] + item['source_types']))
            match['source_urls'] = sorted(set(match['source_urls'] + item['source_urls']))
            if item.get('felt'):
                match['felt'] = True
                if item.get('felt_info'):
                    match['felt_info'] = item['felt_info']
            if item.get('potential_text'):
                match['potential_text'] = item['potential_text']
                match['tsunami'] = item['tsunami']
            if item.get('shakemap'):
                match['shakemap'] = item['shakemap']
            match['significant'] = match['magnitude'] >= 6 or match['tsunami']
    for event in events:
        old = next((p for p in previous if p.get('id') == event['id']), None)
        if old and {k:v for k,v in old.items() if k not in ('last_updated_at', 'first_seen_at')} == {k:v for k,v in event.items() if k not in ('last_updated_at', 'first_seen_at')}:
            event['last_updated_at'] = old.get('last_updated_at', now)
    return events, warnings


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
    if args.fixtures_dir:
        # Offline fixtures preserve the original M5+/felt integration test path.
        feeds = {name:fetch_feed(name,args.fixtures_dir) for name in FEEDS}
        previous = old.get('events', []) if old.get('status') == 'fixture' else []
        events, errors = ingest(previous, feeds, now)
        status = 'fixture'
        source_note = 'Test fixture; not real-time BMKG data.'
    else:
        html = fetch_realtime_html()
        events = parse_realtime_html(html)
        feeds = {}
        feed_errors = []
        for name in FEEDS:
            try:
                feeds[name] = fetch_feed(name)
            except (RuntimeError, ValueError) as exc:
                feed_errors.append(f'{name}: {str(exc)[:140]}')
        previous = old.get('events', []) if old.get('status') == 'live' else []
        events, errors = enrich_realtime(events, feeds, previous, now)
        errors = (errors + feed_errors)[:20]
        status = 'live'
        source_note = '200 gempa terbaru pada tabel real-time BMKG (jumlah aktual dapat kurang dari 200), termasuk episentrum di luar Indonesia; gempa dirasakan dilengkapi dari feed terpisah. Bukan total seluruh gempa dalam periode tersebut.'
    payload = {
        'schema_version': 2,
        'status': status,
        'data_origin': 'realtime_table' if status == 'live' else 'fixtures',
        'checked_at': now,
        'source': 'Badan Meteorologi, Klimatologi, dan Geofisika (BMKG)',
        'coverage_note': source_note,
        'sources': {'realtime':REALTIME_URL, **{k:BASE+v for k,v in FEEDS.items()}},
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
