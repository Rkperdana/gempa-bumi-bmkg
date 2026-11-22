#!/usr/bin/env python3
"""Offline safety and copy tests for BMKG weather draft automation."""
import datetime as dt
from io import BytesIO
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

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
        assert status == "draft"
        assert "featured" not in payload
        assert marker in payload["content"]
        assert event is not None
        self.calls.append((payload, dict(ledger)))
        return {"post_id": 123, "status": "draft",
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
        self.assertNotIn("(RK/D-1)", payload["content"])
        self.assertNotIn("Kecamatan C", payload["content"])

    def test_original_featured_image(self):
        data = render(example())
        self.assertLess(len(data), 500_000)
        im = Image.open(BytesIO(data))
        self.assertEqual(im.size, (1200, 675))
        self.assertEqual(im.format, "JPEG")

    def test_no_duplicate_draft_and_update_same_post(self):
        entry = example()
        state = {"version": 1, "alerts": {}}
        wp = DummyWP()
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
        self.assertEqual(process([entry], "draft", now, wp, state), 1)
        self.assertEqual(process([entry], "draft", now, wp, state), 0)
        self.assertEqual(len(wp.calls), 1)
        updated = dict(entry, description=entry["description"] + " BMKG memperbarui informasi.")
        self.assertNotEqual(fingerprint(entry), fingerprint(updated))
        self.assertEqual(process([updated], "draft", now, wp, state), 1)
        self.assertEqual(len(wp.calls), 2)
        self.assertEqual(wp.calls[-1][1]["post_id"], 123)

    def test_no_auto_publish(self):
        with self.assertRaises(ValueError):
            process([example()], "live", dt.datetime.now(UTC))


if __name__ == "__main__":
    unittest.main()
