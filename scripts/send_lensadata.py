#!/usr/bin/env python3
"""Send validated dashboard events to Lensadata using GitHub Actions secrets."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = 'https://lensadata-ridha.perdanark.chatgpt.site/api/integrations/bmkg/earthquakes'
# Start at activation of the M5+ publication policy; do not publish the archive.
START_AT = '2026-11-12T11:11:48Z'
MAX_BATCH = 50
MAX_BYTES = 256 * 1024


def instant(value):
    result = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Event time must have a timezone')
    return result.astimezone(dt.timezone.utc)


def select_events(snapshot, start_at=START_AT, now=None, include_context=False):
    if snapshot.get('status') != 'live':
        raise ValueError('Refusing to send a preview or unavailable snapshot')
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = instant(start_at)
    selected = {}
    for event in snapshot.get('events', []):
        occurred = instant(event['datetime'])
        magnitude = float(event['magnitude'])
        if not math.isfinite(magnitude) or not 0 <= magnitude <= 10:
            raise ValueError('Invalid magnitude')
        if occurred > now + dt.timedelta(minutes=10):
            raise ValueError('Event time is in the future')
        if not include_context and (occurred < cutoff or not (magnitude >= 5 or event.get('felt') or event.get('felt_info'))):
            continue
        latitude, longitude = float(event['lat']), float(event['lon'])
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError('Invalid event coordinates')
        depth = float(event['depth_km'])
        if not math.isfinite(depth) or not 0 <= depth <= 1000:
            raise ValueError('Invalid event depth')
        location = str(event['region']).strip()
        if not location:
            raise ValueError('Event location is missing')
        event_id = str(event['id']).strip()
        if not event_id:
            raise ValueError('Stable event ID is missing')
        sources = event.get('source_urls') or []
        source = next((url for url in sources if url.startswith('https://www.bmkg.go.id/') or url.startswith('https://data.bmkg.go.id/')), 'https://www.bmkg.go.id/gempabumi/gempabumi-realtime')
        selected[event_id] = {
            'eventId': event_id,
            'occurredAt': occurred.isoformat().replace('+00:00', 'Z'),
            'magnitude': magnitude, 'depthKm': depth,
            'latitude': latitude, 'longitude': longitude, 'location': location,
            'feltText': str(event.get('felt_info') or ''),
            # A false tsunami boolean never becomes an invented "safe" claim.
            'potentialText': str(event.get('potential_text') or ''),
            'sourceUrl': source,
        }
    return sorted(selected.values(), key=lambda row: (row['occurredAt'], row['eventId']))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_events(events, config, dry_run=False, opener=None, sleeper=time.sleep, history=None):
    token = config.get('ingest_token') or ''
    site_token = config.get('sites_token') or ''
    if not token or not site_token:
        raise ValueError('Configure LENSADATA_BMKG_TOKEN and LENSADATA_SITES_TOKEN in GitHub Actions secrets')
    opener = opener or urllib.request.build_opener(NoRedirect())
    receipts = []
    # An empty event set still checks the credentials above, so missing secrets
    # cannot accidentally look like a successful integration.
    for batch_index, offset in enumerate(range(0, len(events), MAX_BATCH)):
        chunk = events[offset:offset + MAX_BATCH]
        body = json.dumps({'events': chunk, 'history': (history or [])[-200:]}, ensure_ascii=False).encode('utf-8')
        if len(body) > MAX_BYTES:
            raise ValueError('Batch exceeds the endpoint size limit')
        payload_hash = hashlib.sha256(body).hexdigest()[:16]
        run_id = str(config.get('run_id') or 'manual')
        batch_id = f'{batch_index}-{payload_hash}'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
            'OAI-Sites-Authorization': f'Bearer {site_token}',
            'X-GitHub-Run-Id': run_id,
            'X-GitHub-Run-Attempt': str(config.get('run_attempt') or '1'),
            'X-Lensadata-Batch': batch_id,
            'X-Lensadata-Source': str(config.get('source') or 'github_actions'),
            'User-Agent': 'Lensadata-BMKG-Sync/1.0',
        }
        if dry_run:
            headers['X-Lensadata-Dry-Run'] = 'true'
        for attempt in range(3):
            try:
                req = urllib.request.Request(ENDPOINT, data=body, headers=headers, method='POST')
                with opener.open(req, timeout=40) as response:
                    if response.headers.get_content_type() != 'application/json':
                        raise ValueError('Endpoint did not return JSON; check private-site access')
                    receipt = json.load(response)
                if not receipt.get('ok') or receipt.get('result', {}).get('rejected', 0):
                    raise ValueError('Lensadata rejected one or more events')
                receipts.append(receipt)
                break
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError(f'Lensadata HTTP {error.code}; check the integration secrets and endpoint') from None
                sleeper(attempt + 1)
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise RuntimeError('Lensadata connection failed after three attempts') from None
                sleeper(attempt + 1)
    return receipts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', default='data/gempa.json')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--config-stdin', action='store_true')
    parser.add_argument('--payload-only', action='store_true')
    args = parser.parse_args()
    config = json.loads(sys.stdin.readline()) if args.config_stdin else {
        'ingest_token': os.environ.get('LENSADATA_BMKG_TOKEN'),
        'sites_token': os.environ.get('LENSADATA_SITES_TOKEN'),
        'run_id': os.environ.get('GITHUB_RUN_ID'),
        'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
    }
    snapshot = json.loads(Path(args.snapshot).read_text(encoding='utf-8'))
    events = select_events(snapshot, os.environ.get('LENSADATA_START_AT', START_AT))
    history = select_events(snapshot, include_context=True)[-200:]
    if args.payload_only:
        print(json.dumps({'events': events, 'history': history}, ensure_ascii=False))
        return
    receipts = send_events(events, config, args.dry_run, history=history)
    print(json.dumps({'selected': len(events), 'dryRun': args.dry_run, 'receipts': receipts}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, RuntimeError, OSError) as error:
        print(f'::error::{error}', file=sys.stderr)
        sys.exit(1)
