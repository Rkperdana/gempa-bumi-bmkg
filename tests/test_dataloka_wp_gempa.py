import datetime as dt
import importlib.util
import io
import re
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
        self.assertEqual(body.count("<p>"), 4)
        self.assertRegex(body, r" \(RK/D-1\)</p><!-- dataloka-bmkg:")
        self.assertNotIn("\n", body)
        self.assertIn("6,20° LS", body)

    def test_daily_summary_only_m5_to_m54(self):
        a = self.event(Magnitude="5.2")
        b = self.event(Magnitude="5.6")
        day = dt.date(2026, 11, 17)
        output = p.daily_article([{"data": a}, {"data": b}], day)
        self.assertIn("Daftar Gempa", output["title"])
        self.assertIn("5,2", output["content"])
        self.assertNotIn("5,6", output["content"])

    def test_daily_signature_and_four_paragraphs(self):
        a = self.event(Magnitude="5.2")
        result = p.daily_article([{"data": a}], dt.date(2026, 11, 17))
        self.assertEqual(result["content"].count("<p>"), 4)
        self.assertRegex(result["content"],
                         r" \(RK/D-1\)</p><!-- dataloka-bmkg-daily:")

    @unittest.skipUnless(importlib.util.find_spec("PIL") is not None, "Pillow tidak dipakai workflow dashboard BMKG")
    def test_map_jpeg_16_by_9_small_and_valid(self):
        from PIL import Image
        from scripts.dataloka_gempa_image import render
        jpg = render(self.event())
        self.assertLess(len(jpg), 500_000)
        with Image.open(io.BytesIO(jpg)) as im:
            self.assertEqual(im.size, (1200, 675))
            self.assertEqual(im.format, "JPEG")

    def test_wordpress_new_live_post_receives_featured_image(self):
        wp = p.WordPress("test_user", "fake_password")
        event = self.event()
        article = p.article(event)
        calls = []
        current_status = {"value": "draft"}
        wp.by_slug = lambda slug: None
        wp.cover_image = lambda quake: 1234

        def fake_call(method, route, params=None, payload=None):
            calls.append((method, route, payload))
            if route == "categories":
                return [{"id": 43, "name": "Berita", "slug": "berita"}]
            if route == "tags":
                return [
                    {"id": 10, "name": "Gempa"},
                    {"id": 11, "name": "BMKG"},
                    {"id": 12, "name": "Episentrum"},
                    {"id": 13, "name": "Seismik"},
                    {"id": 14, "name": "Jawa"},
                ]
            if route in ("posts", "posts/77"):
                if payload:
                    current_status["value"] = payload.get(
                        "status", current_status["value"]
                    )
                return {"id": 77}
            return []
        wp.call = fake_call
        wp.by_id = lambda post_id: {
            "id": post_id,
            "content": {"raw": article["content"]},
            "status": current_status["value"],
            "featured_media": 1234,
            "meta": dict(article["yoast_meta"]),
        }

        result = wp.save(
            article, {}, "publish",
            f"<!-- {p.MARKER}{event['key']} -->", event=event
        )
        creation = next(payload for method, path, payload in calls
                        if method == "POST" and path == "posts")
        self.assertEqual(creation["featured_media"], 1234)
        self.assertEqual(creation["categories"], [43])
        self.assertEqual(creation["tags"], [10, 11, 12, 13, 14])
        self.assertEqual(creation["meta"], article["yoast_meta"])
        self.assertEqual(creation["status"], "draft")
        self.assertNotIn("yoast_meta", creation)
        publication = next(payload for method, path, payload in calls
                           if method == "POST" and path == "posts/77")
        self.assertEqual(publication, {"status": "publish"})
        self.assertEqual(result["media_id"], 1234)
        self.assertEqual(result["status"], "publish")
        self.assertIn("yoast_meta_digest", result)

    def test_no_publication_if_yoast_fields_not_exposed(self):
        wp = p.WordPress("test", "fake")
        event = self.event()
        article = p.article(event)
        calls = []
        wp.by_slug = lambda slug: None
        wp.resolve_tags = lambda names: []
        wp.berita_category_id = lambda: 43
        wp.cover_image = lambda quake: 123

        def fake_call(method, route, params=None, payload=None):
            calls.append((method, route, payload))
            return {"id": 99}
        wp.call = fake_call
        wp.by_id = lambda post_id: {
            "id": post_id, "status": "draft",
            "featured_media": 123, "content": {"raw": article["content"]},
            "meta": {},
        }
        with self.assertRaisesRegex(RuntimeError, "Yoast metadata"):
            wp.save(article, {}, "publish",
                    f"<!-- {p.MARKER}{event['key']} -->", event=event)
        post_writes = [item[2] for item in calls if item[0] == "POST"
                       and item[1].startswith("posts")]
        self.assertEqual(len(post_writes), 1)
        self.assertEqual(post_writes[0]["status"], "draft")

    def test_prior_human_yoast_edits_are_preserved(self):
        wp = p.WordPress("test", "fake")
        event = self.event()
        article = p.article(event)
        found_meta = dict(article["yoast_meta"])
        found_meta["_yoast_wpseo_metadesc"] = "Editorial special description"
        wp.by_slug = lambda slug: {
            "id": 77, "status": "publish", "featured_media": 1234,
            "content": {"raw": article["content"]}, "meta": found_meta,
            "tags": [10], "slug": article["slug"],
        }
        wp.call = lambda *args, **kwargs: self.fail(
            "Must not write a post with manually edited Yoast SEO fields"
        )
        with self.assertRaisesRegex(RuntimeError, "Existing Yoast SEO"):
            wp.save(article, {}, "publish",
                    f"<!-- {p.MARKER}{event['key']} -->", event=event)


    def test_seo_headline_slug_excerpt_and_tags(self):
        event = self.event()
        fields = p.article(event)
        self.assertIn("Gempa M5,6 di Selatan Jawa", fields["title"])
        self.assertIn("BMKG", fields["title"])
        self.assertRegex(
            fields["slug"],
            r"^gempa-selatan-jawa-2026-11-17-[0-9a-f]{8}$",
        )
        self.assertLessEqual(len(fields["excerpt"]), 160)
        self.assertIn("pukul 08.10 WIB", fields["excerpt"])
        self.assertIn("tidak berpotensi tsunami", fields["excerpt"])
        self.assertIn("Jawa", fields["tag_names"])
        self.assertTrue(all(" " not in tag for tag in fields["tag_names"]))
        self.assertEqual(fields["content"].count("<p>"), 4)
        self.assertEqual(
            set(fields["yoast_meta"]), set(p.YOAST_KEYS)
        )
        self.assertEqual(
            fields["yoast_meta"]["_yoast_wpseo_focuskw"],
            "gempa M5,6 di Selatan Jawa",
        )
        self.assertEqual(
            fields["yoast_meta"]["_yoast_wpseo_title"], fields["title"]
        )
        self.assertEqual(
            fields["yoast_meta"]["_yoast_wpseo_metadesc"],
            fields["excerpt"]
        )
        self.assertLessEqual(
            len(fields["yoast_meta"]["_yoast_wpseo_metadesc"]), 160
        )
        self.assertIn("gempa m5,6 di selatan jawa", fields["content"].casefold())
        self.assertRegex(fields["content"], r" \(RK/D-1\)</p><!-- dataloka-bmkg:")

    def test_berita_id_lookup_and_cache(self):
        wp = p.WordPress("test", "fake")
        observed = []

        def fake_call(method, route, params=None, payload=None):
            observed.append((method, route))
            if route == "categories":
                return [
                    {"id": 1, "name": "Uncategorized", "slug": "uncategorized"},
                    {"id": 43, "name": "Berita", "slug": "berita"},
                ]
            return []

        wp.call = fake_call
        self.assertEqual(wp.berita_category_id(), 43)
        self.assertEqual(wp.berita_category_id(), 43)
        self.assertEqual(observed, [("GET", "categories")])

    def test_berita_missing_fails_closed(self):
        wp = p.WordPress("test", "fake")
        wp.call = lambda method, route, params=None, payload=None: []
        with self.assertRaisesRegex(RuntimeError, "Berita"):
            wp.berita_category_id()

    def test_daily_seo_metadata(self):
        record = self.event(Magnitude="5.2")
        fields = p.daily_article([{"data": record}], dt.date(2026, 11, 17))
        self.assertIn("Daftar Gempa M5,0", fields["title"])
        self.assertIn("daftar-gempa-m50-m54-2026-11-17", fields["slug"])
        self.assertLessEqual(len(fields["excerpt"]), 160)
        self.assertIn("BMKG", fields["tag_names"])
        self.assertEqual(
            fields["yoast_meta"]["_yoast_wpseo_metadesc"],
            fields["excerpt"]
        )
        self.assertIn(
            "gempa M5,0–5,4",
            fields["yoast_meta"]["_yoast_wpseo_focuskw"]
        )

    def test_site_is_dataloka_only(self):
        self.assertEqual(p.WP_URL, "https://dataloka.id")


if __name__ == "__main__":
    unittest.main()
