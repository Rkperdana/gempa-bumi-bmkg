import datetime as dt
import importlib.util
import io
import re
import json
import subprocess
import sys
import tempfile
from unittest import mock
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

    def test_every_m55_publishes_regardless_of_tsunami_status(self):
        self.assertEqual(p.status_for(self.event(), "live"), "publish")
        self.assertEqual(p.status_for(self.event(Magnitude="5.5"), "live"), "publish")
        self.assertEqual(p.status_for(self.event(Magnitude="5.4"), "live"), None)
        self.assertEqual(p.status_for(self.event(Magnitude="4.8", Dirasakan="III"), "live"), None)
        self.assertEqual(p.status_for(self.event(), "dry-run"), "publish")
        with self.assertRaises(ValueError):
            p.status_for(self.event(), "drafts")
        for potential in ("", "Tidak berpotensi tsunami",
                          "Berpotensi tsunami", "Peringatan dini tsunami",
                          "Tidak berpotensi tsunami; berpotensi tsunami"):
            with self.subTest(potential=potential):
                event = self.event(Potensi=potential)
                self.assertEqual(p.status_for(event, "live"), "publish")
                body = p.article(event)["content"]
                self.assertEqual(body.count("<p>"), 4)
                self.assertRegex(body, r" \(RK/D-1\)</p><!-- dataloka-bmkg:")
                if potential:
                    self.assertIn(p.escape(potential), body)
                else:
                    self.assertIn("belum tercantum", body)
        self.assertEqual(
            p.status_for(self.event(feed="gempadirasakan.json"), "live"),
            "publish"
        )

    def test_m50_to_m54_collected_without_individual_wordpress_posts(self):
        ignored = [
            self.event(Magnitude="5.4"),
            self.event(Magnitude="5.0", Dirasakan="IV"),
            self.event(Magnitude="4.8", Dirasakan="III"),
        ]
        state = {"version": 1, "events": [], "daily": {}}
        class NoWP:
            def save(self, *args, **kwargs):
                raise AssertionError("M<5.5 must never contact WordPress")
        now = dt.datetime(2026, 11, 17, 1, 55, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=ignored)
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "state.json")
        ):
            p.events_task("live", NoWP(), now)
        self.assertEqual(sorted(x["data"]["magnitude"] for x in state["events"]),
                         [5.0, 5.4])
        self.assertTrue(all("post_id" not in x for x in state["events"]))

    def test_existing_m56_corrected_below_threshold_never_contacts_wp(self):
        old = self.event(Magnitude="5.6")
        corrected = self.event(Magnitude="5.4")
        state = {"version": 1, "events": [
            {"key": old["key"], "data": old, "post_id": 9111,
             "status": "publish", "media_id": 900}
        ], "daily": {}}
        class NoWP:
            def save(self, *args, **kwargs):
                raise AssertionError("Correction to M5.4 must not touch WordPress")
        now = dt.datetime(2026, 11, 17, 1, 55, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[corrected])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "state.json")
        ):
            p.events_task("live", NoWP(), now)
        self.assertEqual(state["events"][0]["post_id"], 9111)

    def test_daily_task_and_drafts_mode_disallowed_at_cli(self):
        for args in (["--mode", "drafts"], ["--task", "invalid"]):
            with self.subTest(args=args):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "dataloka_wp_gempa.py"),
                     *args],
                    capture_output=True, text=True, timeout=10
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("invalid choice", result.stderr)

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
        self.assertTrue(body.startswith("<p><strong>Dataloka.id</strong> - "))
        self.assertRegex(body, r" \(RK/D-1\)</p><!-- dataloka-bmkg:")
        self.assertNotIn("\n", body)
        self.assertIn("6,20° LS", body)

    def test_article_lead_internal_tag_and_plain_bmkg_source(self):
        event = self.event()
        body = p.article(event)["content"]
        paragraphs = body.split("</p>")
        self.assertEqual(body.count("<p>"), 4)
        self.assertTrue(paragraphs[0].startswith(
            '<p><strong>Dataloka.id</strong> - '
            '<a href="https://dataloka.id/tag/gempa/">Gempa</a> M5,6'))
        self.assertEqual(body.count('<a href="https://dataloka.id/tag/gempa/">'), 1)
        self.assertNotIn("<a ", "".join(paragraphs[1:]))
        self.assertIn("bersumber dari data BMKG.", paragraphs[3])
        self.assertNotIn("href=", paragraphs[3])
        self.assertTrue(body.endswith(
            f" (RK/D-1)</p><!-- {p.MARKER}{event['key']} -->"))
        self.assertNotIn("<strong>", p.article(event)["excerpt"])
        self.assertNotIn("<a ", p.article(event)["title"])

    def test_daily_summary_uses_same_editorial_link_style(self):
        quake = self.event(Magnitude="5.2")
        body = p.daily_article([{"data": quake}], dt.date(2026, 11, 17))["content"]
        lead = body.split("</p>", 1)[0]
        self.assertTrue(lead.startswith("<p><strong>Dataloka.id</strong> - "))
        self.assertIn(
            '<a href="https://dataloka.id/tag/gempa/">gempa</a>', lead)
        self.assertEqual(body.count('href='), 1)
        self.assertIn("menggunakan data BMKG", body)
        self.assertNotIn('href="https://data.bmkg.go.id', body)

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
        self.assertTrue(result["content"].startswith("<p><strong>Dataloka.id</strong> - "))
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

    @unittest.skipUnless(importlib.util.find_spec("PIL") is not None,
                         "Pillow diperlukan untuk pengujian generator gambar")
    def test_map_renderer_import_in_direct_actions_script_execution(self):
        # Use a fresh Python process with repo root absent from sys.path.
        # This reproduces `python scripts/dataloka_wp_gempa.py` in GitHub Actions.
        code = """
import importlib.util
import io
import sys
from pathlib import Path
filename = Path(sys.argv[1]).resolve()
root = filename.parents[1]
sys.path[:] = [str(filename.parent)] + [
    value for value in sys.path
    if value and Path(value).resolve() != root and value != str(filename.parent)
]
spec = importlib.util.spec_from_file_location("direct_actions_script", filename)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
assert str(root) not in sys.path
client = publisher.WordPress("test", "fake")
client.call = lambda method, route, params=None, payload=None: (
    [] if method == "GET" else {"id": 99})
publisher.urllib.request.urlopen = lambda *args, **kwargs: io.BytesIO(b'{"id":99}')
event = publisher.normalize({
    "DateTime": "2026-11-17T01:10:10+00:00",
    "Coordinates": "-6.2,106.82",
    "Magnitude": "4.8",
    "Kedalaman": "10 km",
    "Wilayah": "Selatan Jawa",
    "Dirasakan": "III",
}, "gempadirasakan.json")
assert client.cover_image(event) == 99
assert str(root) in sys.path
"""
        outcome = subprocess.run(
            [sys.executable, "-c", code, str(ROOT / "scripts" / "dataloka_wp_gempa.py")],
            cwd=ROOT, text=True, capture_output=True, timeout=35,
        )
        self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)

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
                    {"id": 15, "name": "Featured"},
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
            "slug": article["slug"],
            "tags": [10, 11, 12, 13, 14, 15],
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
        self.assertEqual(creation["tags"], [10, 11, 12, 13, 14, 15])
        self.assertEqual(creation["meta"], article["yoast_meta"])
        self.assertEqual(creation["status"], "draft")
        self.assertNotIn("yoast_meta", creation)
        publication = next(payload for method, path, payload in calls
                           if method == "POST" and path == "posts/77")
        self.assertEqual(publication, {"status": "publish"})
        self.assertEqual(result["media_id"], 1234)
        self.assertEqual(result["status"], "publish")
        self.assertIn("yoast_meta_digest", result)

    def test_existing_major_quake_adds_featured_without_removing_tags(self):
        wp = p.WordPress("test", "fake")
        event = self.event()
        payload = p.article(event)
        existing_tags = [81, 82]
        writes = []
        wp.resolve_tags = lambda names: [15] if "Featured" in names else []
        wp.berita_category_id = lambda: 43
        wp.by_id = lambda post_id: {
            "id": 77,
            "status": "publish",
            "featured_media": 1234,
            "slug": payload["slug"],
            "content": {"raw": payload["content"]},
            "meta": dict(payload["yoast_meta"]),
            "tags": [81, 82, 15] if writes else existing_tags,
        }
        wp.call = lambda method, route, params=None, payload=None: (
            writes.append((method, route, payload)) or {"id": 77})
        ledger = {
            "post_id": 77,
            "status": "publish",
            "media_id": 1234,
            "last_wp_digest": p.hash_value(payload["content"]),
        }
        response = wp.save(
            payload, ledger, "publish",
            f"<!-- {p.MARKER}{event['key']} -->", event=event,
        )
        self.assertEqual(writes[0][1], "posts/77")
        self.assertEqual(writes[0][2]["tags"], [81, 82, 15])
        self.assertEqual(response["status"], "publish")

    def test_missing_featured_tag_prevents_new_major_quake_publication(self):
        wp = p.WordPress("test", "fake")
        event = self.event()
        payload = p.article(event)
        wp.by_slug = lambda slug: None
        wp.resolve_tags = lambda names: []
        wp.call = lambda *args, **kwargs: self.fail("Must not create a new post")
        with self.assertRaisesRegex(RuntimeError, "Featured"):
            wp.save(payload, {}, "publish",
                    f"<!-- {p.MARKER}{event['key']} -->", event=event)

    def test_no_publication_if_yoast_fields_not_exposed(self):
        wp = p.WordPress("test", "fake")
        event = self.event()
        article = p.article(event)
        calls = []
        wp.by_slug = lambda slug: None
        wp.resolve_tags = lambda names: [15] if "Featured" in names else []
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

    def test_post_stays_draft_if_wordpress_rewrites_slug(self):
        wp = p.WordPress("test", "fake")
        event = self.event()
        payload = p.article(event)
        calls = []
        wp.by_slug = lambda slug: None
        wp.resolve_tags = lambda names: [15] if "Featured" in names else []
        wp.berita_category_id = lambda: 43
        wp.cover_image = lambda quake: 123

        def fake_call(method, route, params=None, payload=None):
            calls.append((method, route, payload))
            return {"id": 99}
        wp.call = fake_call
        wp.by_id = lambda post_id: {
            "id": post_id, "status": "draft", "featured_media": 123,
            "content": {"raw": payload["content"]},
            "slug": "unexpected-slug",
            "meta": payload["yoast_meta"],
        }
        with self.assertRaisesRegex(RuntimeError, "SEO slug"):
            wp.save(payload, {}, "publish",
                    f"<!-- {p.MARKER}{event['key']} -->", event=event)
        self.assertEqual([call[1] for call in calls if call[1].startswith("posts")],
                         ["posts"])

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
        self.assertIn("Simak informasi resmi BMKG.", fields["excerpt"])
        self.assertIn("Jawa", fields["tag_names"])
        self.assertIn("Featured", fields["tag_names"])
        self.assertNotIn("Featured", p.article(self.event(Magnitude="5.4"))["tag_names"])
        self.assertTrue(all(" " not in tag for tag in fields["tag_names"]))
        self.assertEqual(fields["content"].count("<p>"), 4)
        self.assertEqual(
            set(fields["yoast_meta"]), set(p.YOAST_KEYS)
        )
        self.assertEqual(
            fields["yoast_meta"]["_yoast_wpseo_focuskw"],
            "gempa M5.6 di Selatan Jawa",
        )
        self.assertNotEqual(
            fields["yoast_meta"]["_yoast_wpseo_title"], fields["title"]
        )
        self.assertIn("2026", fields["yoast_meta"]["_yoast_wpseo_title"])
        self.assertIn("BMKG: Tidak Berpotensi Tsunami", fields["title"])
        self.assertEqual(
            fields["yoast_meta"]["_yoast_wpseo_metadesc"],
            fields["excerpt"]
        )
        self.assertLessEqual(
            len(fields["yoast_meta"]["_yoast_wpseo_metadesc"]), 160
        )
        visible_body = re.sub(r"<[^>]*>", "", fields["content"])
        self.assertIn("gempa m5,6 di selatan jawa", visible_body.casefold())
        self.assertTrue(fields["content"].startswith("<p><strong>Dataloka.id</strong> - "))
        self.assertRegex(fields["content"], r" \(RK/D-1\)</p><!-- dataloka-bmkg:")

    def test_seo_description_exact_bmkg_example_and_dot_keyphrase(self):
        event = self.event(
            feed="gempadirasakan.json",
            DateTime="2026-11-17T00:49:17+00:00",
            Magnitude="4.8", Kedalaman="2 km",
            Wilayah="Pusat gempa berada di laut 49 km timur laut Ruteng, Manggarai",
            Dirasakan="III Kab. Manggarai",
        )
        fields = p.article(event)
        expected_description = (
            "Pusat gempa M4,8 berada di laut 49 km timur laut Ruteng, "
            "Manggarai pada 17 November 2026, pukul 07.49 WIB. "
            "Simak informasi resmi BMKG."
        )
        self.assertEqual(fields["excerpt"], expected_description)
        self.assertEqual(
            fields["yoast_meta"]["_yoast_wpseo_metadesc"],
            expected_description,
        )
        self.assertEqual(
            fields["yoast_meta"]["_yoast_wpseo_focuskw"],
            "gempa M4.8 di Ruteng Manggarai",
        )
        self.assertNotIn(",", fields["yoast_meta"]["_yoast_wpseo_focuskw"])
        self.assertLessEqual(len(expected_description), 160)

    def test_no_duplicate_epicenter_prefix_and_long_meta_stays_under_limit(self):
        event = self.event(
            Wilayah=("Pusat gempa berada di laut 123 km barat laut "
                     "Kabupaten Administrasi Kepulauan Seribu dan pulau-pulau sekitarnya "
                     "di perairan utara Pulau Jawa, Indonesia"),
            Dirasakan="III",
        )
        fields = p.article(event)
        desc = fields["yoast_meta"]["_yoast_wpseo_metadesc"]
        self.assertTrue(desc.startswith("Pusat gempa M5,6 "))
        self.assertNotIn("Pusat gempa M5,6 Pusat gempa", desc)
        self.assertTrue(desc.endswith("Simak informasi resmi BMKG."))
        self.assertIn("17 November 2026, pukul 08.10 WIB.", desc)
        self.assertLessEqual(len(desc), 160)
        focus = fields["yoast_meta"]["_yoast_wpseo_focuskw"]
        self.assertIn("M5.6", focus)
        self.assertNotIn(",", focus)

    def test_bmkg_distance_only_region_keeps_distance_not_invents_sea(self):
        event = self.event(
            Wilayah="130 km BaratDaya MALUKUTENGGARA",
            Magnitude="6.8",
        )
        fields = p.article(event)
        desc = fields["yoast_meta"]["_yoast_wpseo_metadesc"]
        self.assertTrue(desc.startswith(
            "Pusat gempa M6,8 berada 130 km BaratDaya MALUKUTENGGARA"
        ))
        self.assertNotIn("berada di laut", desc)
        self.assertEqual(
            fields["yoast_meta"]["_yoast_wpseo_focuskw"],
            "gempa M6.8 di Maluku Tenggara",
        )

    def test_editorial_headline_felt_manggarai_uses_place_not_raw_bmkg_sentence(self):
        event = self.event(
            feed="gempadirasakan.json",
            Magnitude="4.8",
            Wilayah="Pusat gempa berada di laut 49 km timur laut Ruteng, Manggarai",
            Dirasakan="III Kab. Manggarai")
        result = p.article(event)
        self.assertEqual(
            result["title"],
            "Gempa M4,8 di Ruteng, Manggarai, Terasa hingga III MMI")
        self.assertTrue(result["content"].startswith("<p><strong>Dataloka.id</strong> - "))
        self.assertNotIn("Pusat gempa berada", result["title"])
        self.assertIn("Pusat gempa berada", result["content"])
        self.assertNotEqual(result["title"], result["yoast_meta"]["_yoast_wpseo_title"])

    def test_existing_unedited_draft_gets_new_headline_lead_and_featured_map(self):
        wp = p.WordPress("test_user", "fake_password")
        event = self.event(
            feed="gempadirasakan.json",
            Magnitude="4.8",
            Wilayah="Pusat gempa berada di laut 49 km timur laut Ruteng, Manggarai",
            Dirasakan="III Kab. Manggarai")
        updated = p.article(event)
        previous = dict(updated)
        previous["content"] = updated["content"].replace(
            "<p><strong>Dataloka.id</strong> - ", "<p>", 1)
        previous["title"] = p.seo_title(
            event, "17 November 2026")
        ledger = {
            "post_id": 9057,
            "status": "draft",
            "media_id": 0,
            "last_wp_digest": p.hash_value(previous["content"]),
        }
        writes = []
        image_calls = []
        wp.cover_image = lambda quake: (image_calls.append(quake["key"]) or 881)
        wp.by_id = lambda post_id: {
            "id": post_id, "status": "draft",
            "slug": updated["slug"],
            "title": {"raw": p.seo_title(event, "17 November 2026") if not writes else updated["title"]},
            "content": {"raw": previous["content"] if not writes else updated["content"]},
            "featured_media": 0 if not writes else 881,
            "tags": [10],
            "meta": dict(updated["yoast_meta"]),
        }
        wp.call = lambda method, route, params=None, payload=None: (
            writes.append((method, route, payload)) or {"id": 9057}
        )
        wp.berita_category_id = lambda: 43
        response = wp.save(updated, ledger, "draft",
                           f"<!-- {p.MARKER}{event['key']} -->", event=event)
        self.assertEqual(image_calls, [event["key"]])
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][1], "posts/9057")
        self.assertEqual(writes[0][2]["featured_media"], 881)
        self.assertEqual(writes[0][2]["status"], "draft")
        self.assertEqual(writes[0][2]["title"], updated["title"])
        self.assertEqual(writes[0][2]["content"], updated["content"])
        self.assertNotIn("slug", writes[0][2])
        self.assertEqual(response["media_id"], 881)

    def test_manually_edited_headline_is_not_overwritten_or_given_image(self):
        wp = p.WordPress("test", "fake")
        event = self.event(feed="gempadirasakan.json",
                           Magnitude="4.8", Dirasakan="III")
        updated = p.article(event)
        seen = []
        wp.by_slug = lambda slug: {
            "id": 9110, "status": "draft",
            "slug": updated["slug"],
            "title": {"raw": "Judul Redaksi Khusus yang Sudah Disunting"},
            "content": {"raw": updated["content"]},
            "featured_media": 0,
            "meta": updated["yoast_meta"],
        }
        wp.cover_image = lambda event: seen.append("image") or 800
        wp.call = lambda *a, **k: seen.append("write")
        with self.assertRaisesRegex(p.EditorialConflict, "Title"):
            wp.save(updated, {}, "draft",
                    f"<!-- {p.MARKER}{event['key']} -->", event=event)
        self.assertEqual(seen, [])

    def test_new_draft_also_receives_featured_map(self):
        wp = p.WordPress("test", "fake")
        event = self.event(feed="gempadirasakan.json",
                           Magnitude="4.8", Dirasakan="III")
        payload = p.article(event)
        wp.by_slug = lambda slug: None
        wp.resolve_tags = lambda names: [10]
        wp.berita_category_id = lambda: 43
        wp.cover_image = lambda quake: 801
        writes = []
        wp.call = lambda method, route, params=None, payload=None: (
            writes.append((route, payload)) or {"id": 9100})
        wp.by_id = lambda post_id: {
            "id": post_id, "status": "draft",
            "slug": payload["slug"], "content": {"raw": payload["content"]},
            "featured_media": 801, "meta": dict(payload["yoast_meta"]),
        }
        outcome = wp.save(payload, {}, "draft",
                          f"<!-- {p.MARKER}{event['key']} -->", event=event)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], "posts")
        self.assertEqual(writes[0][1]["featured_media"], 801)
        self.assertEqual(outcome["media_id"], 801)

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

    def test_human_edited_draft_does_not_block_next_m55_post(self):
        old = self.event(
            feed="gempadirasakan.json",
            DateTime="2026-11-17T01:15:10+00:00",
            Magnitude="2.6", Dirasakan="III Sukabumi")
        new = self.event(
            DateTime="2026-11-17T01:32:10+00:00",
            Coordinates="-7.20,107.82", Magnitude="5.6")
        state = {
            "version": 1, "daily": {},
            "events": [{"key": old["key"], "data": old,
                        "post_id": 9041, "status": "draft"}],
        }
        calls = []

        class FakeWP:
            def save(self, payload, record, status, marker, event=None):
                calls.append((event["key"], status))
                if record.get("post_id") == 9041:
                    raise p.EditorialConflict(
                        "Post 9041 edited manually; refusing overwrite")
                return {
                    "post_id": 9200,
                    "status": "publish",
                    "media_id": 500,
                    "last_wp_digest": p.hash_value(payload["content"]),
                    "last_payload_digest": p.hash_value(json.dumps(
                        payload, ensure_ascii=False, sort_keys=True)),
                }

        now = dt.datetime(2026, 11, 17, 1, 55, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[old, new])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "ledger.json")
        ):
            p.events_task("live", FakeWP(), now)
            saved = json.loads((Path(temp) / "ledger.json").read_text())
        # The previously created draft is NEVER queried or rewritten.
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "publish")
        self.assertEqual(next(item for item in saved["events"]
                              if item.get("post_id") == 9041)["status"], "draft")
        self.assertEqual(next(item for item in saved["events"]
                              if item.get("post_id") == 9200)["status"], "publish")

    def test_unchanged_existing_article_without_media_never_contacts_wordpress(self):
        event = self.event()
        state = {"version": 1, "daily": {}, "events": [
            {"key": event["key"], "data": event, "post_id": 9041,
             "status": "publish", "media_id": 0, "last_payload_digest": "old"}
        ]}

        class NoWP:
            def save(self, *args, **kwargs):
                raise AssertionError("Unchanged event must not touch WordPress")

        now = dt.datetime(2026, 11, 17, 1, 55, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[event])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "ledger.json")
        ):
            p.events_task("live", NoWP(), now)
        self.assertEqual(state["events"][0]["post_id"], 9041)
        self.assertEqual(len(state["events"][0]["published_versions"]), 1)

    def test_revised_parameters_create_one_new_post_without_editing_original(self):
        event = self.event()
        revised = self.event(Kedalaman="12 km", Magnitude="5.7")
        state = {"version": 1, "daily": {}, "events": [
            {"key": event["key"], "data": event, "post_id": 9500,
             "status": "publish", "media_id": 120}
        ]}
        calls = []

        class RecorderWP:
            def save(self, payload, ledger, status, marker, event=None):
                calls.append((payload, ledger, status, marker))
                return {"post_id": 9501, "status": status, "media_id": 121}

        now = dt.datetime(2026, 11, 17, 1, 55, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "ledger.json"
            dest.write_text(json.dumps(state), encoding="utf-8")
            with mock.patch.object(p, "get_events", return_value=[revised]), (
                mock.patch.object(p, "STATE", dest)
            ):
                p.events_task("live", RecorderWP(), now)
                p.events_task("live", RecorderWP(), now)
            saved = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], {})  # Create new, never update post 9500
        self.assertIn("-pembaruan-", calls[0][0]["slug"])
        self.assertIn("Pembaruan BMKG:", calls[0][0]["title"])
        self.assertIn(":revision:", calls[0][3])
        self.assertEqual(saved["events"][0]["post_id"], 9500)
        self.assertEqual(len(saved["events"][0]["published_versions"]), 2)

    def test_feed_source_bookkeeping_does_not_create_duplicate_articles(self):
        old = self.event()
        incoming = dict(old, sources=["realtime", "gempaterkini.json"])
        state = {"version": 1, "daily": {}, "events": [
            {"key": old["key"], "data": old, "post_id": 9500,
             "status": "publish", "media_id": 120}
        ]}

        class NoWP:
            def save(self, *args, **kwargs):
                raise AssertionError("Feed bookkeeping is not a factual revision")

        now = dt.datetime(2026, 11, 17, 1, 55, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[incoming])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "ledger.json")
        ):
            p.events_task("live", NoWP(), now)

    def test_draft_major_earthquake_becomes_separate_live_article(self):
        event = self.event()
        state = {"version": 1, "daily": {}, "events": [
            {"key": event["key"], "data": event, "post_id": 9500,
             "status": "draft", "media_id": 120}
        ]}
        writes = []

        class RecorderWP:
            def save(self, payload, ledger, status, marker, event=None):
                writes.append((payload["slug"], ledger, status))
                return {"post_id": 9501, "status": status, "media_id": 121}

        now = dt.datetime(2026, 11, 17, 1, 55, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[event])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "ledger.json")
        ):
            p.events_task("live", RecorderWP(), now)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][1], {})
        self.assertEqual(writes[0][2], "publish")
        self.assertIn("-pembaruan-", writes[0][0])

    def test_api_failure_still_fails_workflow(self):
        event = self.event()
        state = {"version": 1, "daily": {}, "events": []}

        class BrokenWP:
            def save(self, *args, **kwargs):
                raise RuntimeError("WordPress returned HTTP 403")

        now = dt.datetime(2026, 11, 17, 1, 55, tzinfo=dt.timezone.utc)
        # Never let a unit test overwrite the real publisher state file.
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[event])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "isolated-test-state.json")
        ):
            with mock.patch("sys.stderr", new_callable=io.StringIO) as errors:
                with self.assertRaisesRegex(RuntimeError, "1 BMKG events still need WordPress retry"):
                    p.events_task("live", BrokenWP(), now)
                self.assertIn("HTTP 403", errors.getvalue())

    def test_below_threshold_ignored_without_backfilling_old_m71(self):
        # M4.8 is ignored, M7.1 older than 24h is not backfilled.
        # Only the fresh M5.6 goes live.
        felt = self.event(
            feed="gempadirasakan.json",
            DateTime="2026-11-17T00:49:17+00:00",
            Coordinates="-8.22,120.66",
            Magnitude="4.8", Kedalaman="2 km",
            Wilayah="Pusat gempa berada di laut 49 km timur laut Ruteng, Manggarai",
            Dirasakan="III Kab. Manggarai")
        old_71 = self.event(
            DateTime="2026-11-14T21:11:20+00:00",
            Coordinates="-6.03,131.62", Magnitude="7.1",
            Wilayah="130 km BaratDaya MALUKUTENGGARA",
            Dirasakan="III Saumlaki")
        new_56 = self.event(
            DateTime="2026-11-17T07:50:00+00:00",
            Coordinates="-2.99,129.71", Magnitude="5.6",
            Wilayah="Perairan Maluku", Dirasakan="")
        small_unfelt = self.event(
            DateTime="2026-11-17T07:51:00+00:00",
            Coordinates="2.10,119.20", Magnitude="4.9",
            Wilayah="Laut Sulawesi", Dirasakan="")
        creates = []
        class WP:
            def save(self, payload, record, status, marker, event=None):
                creates.append((event["magnitude"], status))
                return {
                    "post_id": 9500 + len(creates),
                    "status": status,
                    "media_id": 777 if status == "publish" else 0,
                    "last_payload_digest": p.hash_value(json.dumps(
                        payload, ensure_ascii=False, sort_keys=True)),
                }
        now = dt.datetime(2026, 11, 17, 8, 45, tzinfo=dt.timezone.utc)
        state = {"events": [], "daily": {}}
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[
                felt, old_71, new_56, small_unfelt])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "state.json")
        ):
            p.events_task("live", WP(), now)
            persisted = json.loads((Path(temp) / "state.json").read_text())
        self.assertEqual(creates, [(5.6, "publish")])
        self.assertEqual(len([x for x in persisted["events"] if x.get("post_id")]), 1)
        self.assertTrue(all(x["data"]["magnitude"] >= 5.5 for x in persisted["events"]))
        self.assertFalse(any(x.get("post_id") and x["data"]["magnitude"] == 7.1
                             for x in persisted["events"]))

    def test_m55_old_event_is_not_backfilled(self):
        felt = self.event(
            DateTime="2026-11-14T18:00:00+00:00",
            Magnitude="5.5", Dirasakan="III")
        now = dt.datetime(2026, 11, 17, 8, 45, tzinfo=dt.timezone.utc)
        state = {"events": [], "daily": {}}
        class WP:
            def save(self, *args, **kwargs):
                raise AssertionError("Stale M5.5 must not be created")
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[felt])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "state.json")
        ):
            p.events_task("live", WP(), now)
        self.assertIsNone(state["events"][0].get("post_id"))


    def test_delayed_major_event_within_24h_is_published_exactly_once(self):
        quake = self.event(
            DateTime="2026-11-17T00:10:00+00:00", Magnitude="5.8")
        now = dt.datetime(2026, 11, 17, 10, 15, tzinfo=dt.timezone.utc)
        state = {"version": 1, "events": [], "daily": {}}
        sends = []

        class WP:
            def save(self, payload, ledger, status, marker, event=None):
                sends.append((event["key"], status))
                return {"post_id": 9911, "status": "publish", "media_id": 9912}

        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[quake])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "state.json")
        ):
            p.events_task("live", WP(), now)
            p.events_task("live", WP(), now + dt.timedelta(minutes=10))
        self.assertEqual(sends, [(quake["key"], "publish")])
        self.assertEqual(len(state["events"]), 1)
        self.assertEqual(state["events"][0]["post_id"], 9911)

    def test_major_event_missed_after_24h_raises_action_alert(self):
        quake = self.event(
            DateTime="2026-11-16T01:00:00+00:00", Magnitude="6.1")
        now = dt.datetime(2026, 11, 17, 08, 45, tzinfo=dt.timezone.utc)
        state = {"version": 1, "events": [], "daily": {}}

        class NoWP:
            def save(self, *args, **kwargs):
                raise AssertionError("Stale major earthquake requires editorial review")

        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[quake])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "state.json")
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            with self.assertRaisesRegex(RuntimeError, "missed the 24h publication window"):
                p.events_task("live", NoWP(), now)
            self.assertIn("::error::Unpublished M6.1", stdout.getvalue())
        self.assertIsNone(state["events"][0].get("post_id"))

    def test_daily_draft_created_once_for_collected_m50_to_m54(self):
        quake = self.event(
            DateTime="2026-11-17T04:00:00+00:00", Magnitude="5.3")
        now = dt.datetime(2026, 11, 17, 18, 15, tzinfo=dt.timezone.utc)
        state = {"version": 1, "events": [], "daily": {}}
        sends = []

        class WP:
            def save(self, payload, ledger, status, marker, event=None):
                sends.append((payload["slug"], status, marker))
                return {"post_id": 9913, "status": status}

        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[quake])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "state.json")
        ):
            p.events_task("live", WP(), now)
            p.daily_task("live", WP(), now)
            p.daily_task("live", WP(), now)
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0][1], "draft")
        self.assertEqual(sends[0][0], "daftar-gempa-m50-m54-2026-11-17")
        self.assertIn("dataloka-bmkg-daily:2026-11-17", sends[0][2])
        self.assertEqual(state["daily"]["2026-11-17"]["post_id"], 9913)

    def test_scheduler_gap_is_reported_in_action_log(self):
        state = {"version": 1, "events": [], "daily": {},
                 "last_checked_at": "2026-11-17T06:00:00Z"}
        now = dt.datetime(2026, 11, 17, 8, 45, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "state.json")
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            p.events_task("live", None, now)
            self.assertIn("::warning::Dataloka earthquake check delayed",
                          stdout.getvalue())
        self.assertEqual(state["last_checked_at"], "2026-11-17T08:45:00Z")

    def test_bmkg_transient_timeout_is_retried(self):
        class FakeResponse(io.BytesIO):
            status = 200
        doc = {"Infogempa": {"gempa": [RAW]}}
        response = FakeResponse(json.dumps(doc).encode("utf-8"))
        with mock.patch.object(p.urllib.request, "urlopen", side_effect=[
            TimeoutError("temporary timeout"), response
        ]) as urlopen, mock.patch.object(p.time, "sleep") as sleep:
            self.assertEqual(p.fetch_feed("gempaterkini.json"), doc)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_partial_bmkg_feed_error_does_not_block_other_official_feeds(self):
        def fake_fetch(feed):
            if feed == "gempadirasakan.json":
                raise TimeoutError("BMKG temporarily unavailable")
            return {"Infogempa": {"gempa": [RAW]}}
        with mock.patch.object(p, "fetch_feed", side_effect=fake_fetch):
            events = p.get_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["magnitude"], 5.6)

    def test_json_sources_only_no_interface_or_snapshot(self):
        normal = self.event(Magnitude="5.8", Wilayah="Sulawesi")
        feed_doc = {"Infogempa": {"gempa": [{
            "DateTime": normal["datetime"],
            "Coordinates": f"{normal['lat']},{normal['lon']}",
            "Magnitude": normal["magnitude"],
            "Kedalaman": f"{normal['depth_km']} km",
            "Wilayah": normal["region"],
        }]}}
        with mock.patch.object(p, "fetch_feed", return_value=feed_doc) as fetcher, (
            mock.patch("urllib.request.urlopen", side_effect=AssertionError(
                "Only mocked official JSON fetcher may be used"))
        ):
            result = p.get_events()
        self.assertEqual(len(result), 1)
        self.assertGreaterEqual(fetcher.call_count, 3)
        self.assertEqual(set(result[0]["sources"]), set(p.FEEDS))

    def test_no_html_fallback_when_json_feeds_fail(self):
        with mock.patch.object(p, "fetch_feed",
                               side_effect=TimeoutError("JSON unavailable")):
            with self.assertRaisesRegex(RuntimeError, "All official BMKG JSON feeds unavailable"):
                p.get_events()

    def test_json_m55_keeps_featured_editorial_article(self):
        event = self.event(Magnitude="5.8")
        result = p.article(event)
        self.assertIn("Featured", result["tag_names"])
        self.assertEqual(p.status_for(event, "live"), "publish")

    def test_wordpress_retries_get_but_never_post(self):
        wp = p.WordPress("fake-test-user", "fake-test-password")
        class FakeResponse(io.BytesIO):
            status = 200
        with mock.patch.object(p.urllib.request, "urlopen", side_effect=[
            TimeoutError("temporary read timeout"), FakeResponse(b'[]')
        ]) as urlopen, mock.patch.object(p.time, "sleep") as sleep:
            self.assertEqual(wp.call("GET", "posts"), [])
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(urlopen.call_args_list[0].kwargs["timeout"], 45)
        sleep.assert_called_once_with(1)
        with mock.patch.object(p.urllib.request, "urlopen",
                               side_effect=TimeoutError("write timeout")) as urlopen:
            with self.assertRaisesRegex(RuntimeError, "WordPress network error"):
                wp.call("POST", "posts", payload={"status": "draft"})
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(urlopen.call_args_list[0].kwargs["timeout"], 35)

    def test_single_wordpress_failure_does_not_block_other_events(self):
        felt = self.event(
            feed="gempaterkini.json",
            DateTime="2026-11-17T08:00:17+00:00",
            Coordinates="-8.22,120.66", Magnitude="5.7",
            Dirasakan="III Kab. Manggarai")
        fresh = self.event(
            DateTime="2026-11-17T07:50:00+00:00",
            Coordinates="-2.99,129.71", Magnitude="5.6",
            Wilayah="Perairan Maluku")
        calls = []
        class WP:
            def save(self, payload, record, status, marker, event=None):
                calls.append((event["magnitude"], status))
                if event["magnitude"] == 5.7:
                    raise RuntimeError("WordPress network error on GET posts: TimeoutError")
                return {"post_id": 9501, "status": "publish", "media_id": 101,
                        "last_payload_digest": p.hash_value(json.dumps(
                            payload, ensure_ascii=False, sort_keys=True))}
        state = {"events": [], "daily": {}}
        now = dt.datetime(2026, 11, 17, 8, 45, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[felt, fresh])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "state.json")
        ):
            with self.assertRaisesRegex(RuntimeError, "1 BMKG events"):
                p.events_task("live", WP(), now)
            saved = json.loads((Path(temp) / "state.json").read_text())
        self.assertEqual(calls, [(5.7, "publish"), (5.6, "publish")])
        self.assertEqual([x["post_id"] for x in saved["events"] if x.get("post_id")],
                         [9501])

    def test_site_is_dataloka_only(self):
        self.assertEqual(p.WP_URL, "https://dataloka.id")


if __name__ == "__main__":
    unittest.main()
