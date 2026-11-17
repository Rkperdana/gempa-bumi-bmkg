import datetime as dt
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dataloka_wp", ROOT / "scripts" / "dataloka_wp_gempa.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

RAW = {
    "DateTime": "2026-11-17T01:10:10+00:00",
    "Coordinates": "-6.20,106.82",
    "Magnitude": "5.6",
    "Kedalaman": "10 km",
    "Wilayah": "Selatan Jawa",
    "Potensi": "Tidak berpotensi tsunami",
    "Dirasakan": "",
}


class PublisherTests(unittest.TestCase):
    def event(self, feed="gempaterkini.json", **changes):
        return p.normalize(dict(RAW, **changes), feed)

    def test_live_only_m55_with_clear_confirmation(self):
        self.assertEqual(p.status_for(self.event(), "live"), "publish")
        self.assertEqual(p.status_for(self.event(), "drafts"), "draft")
        self.assertEqual(p.status_for(self.event(Magnitude="5.4"), "live"), "draft")
        self.assertEqual(p.status_for(self.event(Potensi=""), "live"), "draft")
        self.assertEqual(p.status_for(self.event(Potensi="Berpotensi tsunami"), "live"), "draft")
        self.assertEqual(p.status_for(self.event(Potensi="Tidak berpotensi tsunami; berpotensi tsunami"), "live"), "draft")
        self.assertEqual(p.status_for(self.event(feed="gempadirasakan.json"), "live"), "draft")

    def test_fuzzy_match_and_stable_key(self):
        old = self.event()
        revised = self.event(Magnitude="5.7", Kedalaman="12 km")
        self.assertTrue(p.same_event(old, revised))
        merged = p.merge(old, revised)
        self.assertEqual(merged["key"], old["key"])
        self.assertEqual(merged["magnitude"], 5.7)

    def test_article_attribution_and_escaping(self):
        event = self.event(Wilayah="<b>Selatan Jawa</b>")
        body = p.article(event)["content"]
        self.assertIn("BMKG", body)
        self.assertIn("<!-- dataloka-bmkg:", body)
        self.assertIn("&lt;b&gt;Selatan Jawa&lt;/b&gt;", body)
        self.assertNotIn("RKP", body)
        self.assertNotIn("LD1", body)

    def test_daily_summary_only_m5_to_m54(self):
        a = self.event(Magnitude="5.2")
        b = self.event(Magnitude="5.6")
        day = dt.date(2026, 11, 17)
        output = p.daily_article([{"data": a}, {"data": b}], day)
        self.assertIn("Ringkasan", output["title"])
        self.assertIn("5,2", output["content"])
        self.assertNotIn("5,6", output["content"])

    def test_site_is_dataloka_only(self):
        self.assertEqual(p.WP_URL, "https://dataloka.id")


if __name__ == "__main__":
    unittest.main()
