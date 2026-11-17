import datetime as dt
import importlib.util
import io
import re
import json
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
        self.assertEqual(p.status_for(self.event(), "drafts"), "draft")
        self.assertEqual(p.status_for(self.event(Magnitude="5.4"), "live"), "draft")
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
            "slug": article["slug"],
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

    def test_post_stays_draft_if_wordpress_rewrites_slug(self):
        wp = p.WordPress("test", "fake")
        event = self.event()
        payload = p.article(event)
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
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][1], "publish")
        self.assertEqual(next(item for item in saved["events"]
                              if item.get("post_id") == 9041)["status"], "draft")
        self.assertEqual(next(item for item in saved["events"]
                              if item.get("post_id") == 9200)["status"], "publish")

    def test_api_failure_still_fails_workflow(self):
        event = self.event()
        state = {"version": 1, "daily": {}, "events": []}

        class BrokenWP:
            def save(self, *args, **kwargs):
                raise RuntimeError("WordPress returned HTTP 403")

        now = dt.datetime(2026, 11, 17, 1, 55, tzinfo=dt.timezone.utc)
        with mock.patch.object(p, "get_events", return_value=[event]), (
            mock.patch.object(p, "read_state", return_value=state)
        ):
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                p.events_task("live", BrokenWP(), now)

    def test_delayed_felt_m48_becomes_draft_without_backfilling_old_m71(self):
        # At 15.45 WIB, Ruteng M4.8 is nearly eight hours old, so it must
        # enter drafts; the earlier M7.1 is not retroactively published.
        felt = self.event(
            feed="gempadirasakan.json",
            DateTime="2026-11-17T00:49:17+00:00",
            Coordinates="-8.22,120.66",
            Magnitude="4.8", Kedalaman="2 km",
            Wilayah="Pusat gempa berada di laut 49 km timur laut Ruteng, Manggarai",
            Dirasakan="III Kab. Manggarai")
        old_71 = self.event(
            DateTime="2026-11-16T21:11:20+00:00",
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
        self.assertEqual(creates, [(4.8, "draft"), (5.6, "publish")])
        self.assertEqual(len([x for x in persisted["events"] if x.get("post_id")]), 2)
        self.assertFalse(any(x.get("post_id") and x["data"]["magnitude"] == 7.1
                             for x in persisted["events"]))

    def test_draft_window_expires_after_twelve_hours(self):
        felt = self.event(
            DateTime="2026-11-16T18:00:00+00:00",
            Magnitude="4.8", Dirasakan="III")
        now = dt.datetime(2026, 11, 17, 8, 45, tzinfo=dt.timezone.utc)
        state = {"events": [], "daily": {}}
        class WP:
            def save(self, *args, **kwargs):
                self.fail("Stale draft should not be created")
        with tempfile.TemporaryDirectory() as temp, (
            mock.patch.object(p, "get_events", return_value=[felt])
        ), mock.patch.object(p, "read_state", return_value=state), (
            mock.patch.object(p, "STATE", Path(temp) / "state.json")
        ):
            p.events_task("live", WP(), now)
        self.assertIsNone(state["events"][0].get("post_id"))

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
            feed="gempadirasakan.json",
            DateTime="2026-11-17T00:49:17+00:00",
            Coordinates="-8.22,120.66", Magnitude="4.8",
            Dirasakan="III Kab. Manggarai")
        fresh = self.event(
            DateTime="2026-11-17T07:50:00+00:00",
            Coordinates="-2.99,129.71", Magnitude="5.6",
            Wilayah="Perairan Maluku")
        calls = []
        class WP:
            def save(self, payload, record, status, marker, event=None):
                calls.append((event["magnitude"], status))
                if event["magnitude"] == 4.8:
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
        self.assertEqual(calls, [(4.8, "draft"), (5.6, "publish")])
        self.assertEqual([x["post_id"] for x in saved["events"] if x.get("post_id")],
                         [9501])

    def test_site_is_dataloka_only(self):
        self.assertEqual(p.WP_URL, "https://dataloka.id")


if __name__ == "__main__":
    unittest.main()
