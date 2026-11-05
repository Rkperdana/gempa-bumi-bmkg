#!/usr/bin/env python3
"""Minimal headless browser smoke test for the Dataloka map (GitHub Actions)."""
import functools
import http.server
import pathlib
import re
import shutil
import subprocess
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    browser = next((candidate for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser')
                    if (candidate := shutil.which(name))), None)
    if not browser:
        print('No browser available on runner; static-map unit tests still apply.')
        return
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/'
    try:
        args = [browser, '--headless', '--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage',
                '--no-first-run', '--disable-extensions', '--virtual-time-budget=7000',
                '--dump-dom', url]
        result = subprocess.run(args, capture_output=True, text=True, timeout=40, check=False)
        if result.returncode:
            raise RuntimeError('Chrome failed: ' + result.stderr[-1200:])
        dom = result.stdout
        land = re.search(r'<g id="mapLand">([\s\S]*?)</g>', dom)
        if land is None or land.group(1).count('<path') < 150:
            raise AssertionError('Detailed 38-province GeoJSON map did not render in browser')
        points = len(re.findall(r'class="quake-point(?: selected)?"', dom))
        if points < 1:
            raise AssertionError('Earthquake markers did not load in browser')
        if 'class="workspace explorer-grid"' not in dom or 'id="detailCard"' not in dom:
            raise AssertionError('Explorer layout or floating detail missing')
        statuses = ('Sinkronisasi aktif', 'Sinkronisasi data lengkap terlambat',
                    'Feed BMKG langsung aktif')
        if not any(status in dom for status in statuses):
            raise AssertionError('Live data/staleness indicator did not render')
        if 'Feed penting ' in dom:
            print('Official BMKG JSON feeds are reachable from browser (CORS verified).')
        else:
            print('Warning: direct BMKG JSON feed was not confirmed in headless browser.')
        print(f'Browser smoke passed: {land.group(1).count("<path")} island polygons, {points} epicenter markers.')
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
