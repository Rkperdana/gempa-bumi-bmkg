#!/usr/bin/env python3
"""Offline safety and copy tests for BMKG weather live publisher."""
import datetime as dt
from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest import mock
import urllib.error
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import dataloka_wp_cuaca as pub

from dataloka_wp_cuaca import (
    UTC, active, article, parse_cap, parse_rss, process, require_official_url,
    fingerprint,
)
from dataloka_cuaca_image import render
from PIL import Image

SOURCE = "https://www.bmkg.go.id/alerts/nowcast/id/CJB20251013001_alert.xml"
FIXTURE = ROOT / "tests" / "fixtures" / "nowcast-sample.xml"


def example():
    return parse_cap(FIXTURE.read_bytes(), SOURCE)


class DummyWP:
    def __init__(self):
        self.calls = []

    def save(self, payload, ledger, status, marker, event=None):
        assert status == "publish"
        assert "Featured" in payload["tag_names"]
        assert marker in payload["content"]
        assert event is not None
        self.calls.append((payload, dict(ledger)))
        return {"post_id": 123, "status": "publish",
                "media_id": 456, "last_wp_digest": "abc",
                "yoast_meta_digest": "xyz"}


class WeatherTests(unittest.TestCase):
    def test_rss_ignores_unofficial_links(self):
        rss = (f"<rss><channel><item><link>{SOURCE}</link></item>"
               "<item><link>http://evil.invalid/attack</link></item>"
               "</channel></rss>")
        self.assertEqual(len(parse_rss(rss)), 1)
        with self.assertRaises(ValueError):
            require_official_url("https://www.bmkg.go.id.evil.invalid/alerts/nowcast/id/X_alert.xml")

    def test_official_rss_api_path_and_fallback(self):
        self.assertEqual(pub.RSS_URL, "https://www.bmkg.go.id/alerts/nowcast/id")
        self.assertEqual(pub.RSS_FALLBACK_URL,
                         "https://www.bmkg.go.id/alerts/nowcast/id/rss.xml")
        rss = f"<rss><channel><item><link>{SOURCE}</link></item></channel></rss>"
        with mock.patch.object(pub, "fetch_xml", side_effect=[
                urllib.error.HTTPError(pub.RSS_URL, 404, "not found", {}, None),
                rss.encode("utf-8")]) as fetch:
            items = parse_rss(pub.fetch_rss())
        self.assertEqual(len(items), 1)
        self.assertEqual(fetch.call_args_list[0].args[0], pub.RSS_URL)
        self.assertEqual(fetch.call_args_list[1].args[0], pub.RSS_FALLBACK_URL)

    def test_html_success_response_falls_back_to_official_rss(self):
        rss = f"<rss><channel><item><link>{SOURCE}</link></item></channel></rss>"
        with mock.patch.object(pub, "fetch_xml", side_effect=[
                b"<html><body>not an RSS feed</body></html>", rss.encode()]) as fetch:
            items = parse_rss(pub.fetch_rss())
        self.assertEqual(len(items), 1)
        self.assertEqual(fetch.call_count, 2)

    def test_no_fallback_for_forbidden_response(self):
        with mock.patch.object(pub, "fetch_xml", side_effect=urllib.error.HTTPError(
                pub.RSS_URL, 403, "forbidden", {}, None)) as fetch:
            with self.assertRaises(urllib.error.HTTPError):
                pub.fetch_rss()
        self.assertEqual(fetch.call_count, 1)

    def test_cap_details_and_region_exact(self):
        entry = example()
        self.assertEqual(entry["region"], "Jawa Barat")
        self.assertEqual(entry["event"], "Hujan Lebat dan Petir")
        self.assertEqual(entry["severity"], "Moderate")
        self.assertTrue(entry["identifier"].startswith("EXAMPLE"))
        self.assertNotIn("kota terdampak", entry["description"].lower())

    def test_lifecycle_reject_expired_or_unverified(self):
        entry = example()
        inside = dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
        late = dt.datetime(2026, 11, 22, 7, 0, tzinfo=UTC)
        self.assertTrue(active(entry, inside))
        self.assertFalse(active(entry, late))
        entry["certainty"] = "Unlikely"
        self.assertFalse(active(entry, inside))

    def test_safe_copy_complete_seo(self):
        entry = example()
        payload = article(entry)
        self.assertIn("Jawa Barat", payload["title"])
        self.assertIn("Sumber: BMKG", payload["content"])
        self.assertEqual(payload["content"].count("<p>"), 5)
        self.assertEqual(payload["content"].count("</p>"), 5)
        self.assertIn(SOURCE, payload["content"])
        self.assertIn("dataloka-nowcast:", payload["content"])
        self.assertEqual(set(payload["yoast_meta"]), {
            "_yoast_wpseo_focuskw", "_yoast_wpseo_title", "_yoast_wpseo_metadesc"})
        self.assertLessEqual(len(payload["excerpt"]), 300)
        self.assertEqual(payload["tag_names"].count("Featured"), 1)
        self.assertNotIn("(RK/D-1)", payload["content"])
        self.assertNotIn("Kecamatan C", payload["content"])

    def test_original_featured_image(self):
        data = render(example())
        self.assertLess(len(data), 500_000)
        im = Image.open(BytesIO(data))
        self.assertEqual(im.size, (1200, 675))
        self.assertEqual(im.format, "JPEG")

    def test_no_duplicate_publish_and_update_same_post(self):
        entry = example()
        state = {"version": 1, "alerts": {}}
        wp = DummyWP()
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
        self.assertEqual(process([entry], "live", now, wp, state), 1)
        self.assertEqual(process([entry], "live", now, wp, state), 0)
        self.assertEqual(len(wp.calls), 1)
        updated = dict(entry, description=entry["description"] + " BMKG memperbarui informasi.")
        self.assertNotEqual(fingerprint(entry), fingerprint(updated))
        self.assertEqual(process([updated], "live", now, wp, state), 1)
        self.assertEqual(len(wp.calls), 2)
        self.assertEqual(wp.calls[-1][1]["post_id"], 123)

    def test_only_explicit_live_mode_can_publish(self):
        with self.assertRaises(ValueError):
            process([example()], "draft", dt.datetime.now(UTC))

    def test_no_publishing_expired_alert(self):
        state = {"version": 1, "alerts": {}}
        wp = DummyWP()
        self.assertEqual(process([example()], "live",
            dt.datetime(2026, 11, 22, 7, 0, tzinfo=UTC), wp, state), 0)
        self.assertFalse(wp.calls)


if __name__ == "__main__":
    unittest.main()
