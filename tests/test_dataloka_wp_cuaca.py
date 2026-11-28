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
        assert "Featured" not in payload["tag_names"]
        assert marker in payload["content"]
        assert event is not None
        self.calls.append((payload, dict(ledger)))
        return {"post_id": ledger.get("post_id") or 122 + len(self.calls), "status": "publish",
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
        self.assertIn("<strong>Sumber:</strong>", payload["content"])
        self.assertIn('>peringatan BMKG</a>', payload["content"])
        self.assertEqual(payload["content"].count("<p>"), 4)
        self.assertEqual(payload["content"].count("</p>"), 4)
        self.assertIn('<p><strong>Sumber:</strong>', payload["content"])
        self.assertEqual(payload["content"].count("<li>"), 1)
        self.assertNotIn("Sumber:", payload["content"].split("<p>")[3])
        self.assertIn(SOURCE, payload["content"])
        self.assertIn("dataloka-nowcast:", payload["content"])
        self.assertEqual(set(payload["yoast_meta"]), {
            "_yoast_wpseo_focuskw", "_yoast_wpseo_title", "_yoast_wpseo_metadesc"})
        self.assertLessEqual(len(payload["excerpt"]), 300)
        self.assertNotIn("Featured", payload["tag_names"])
        self.assertEqual(payload["tag_names"], ["BMKG", "Cuaca", "Peringatan"])
        self.assertNotIn("(RK/D-1)", payload["content"])
        self.assertNotIn("Kecamatan C", payload["content"])

    def test_jabodetabek_warning_uses_stable_period_slug(self):
        entry = dict(example(), region="Jakarta",
                     url="https://www.bmkg.go.id/alerts/nowcast/id/CJK20261122001_alert.xml",
                     description="Hujan di sebagian wilayah Jakarta, khususnya di BOGOR SELATAN.")
        payload = article(entry)
        self.assertIn("Cuaca Jabodetabek", payload["title"])
        self.assertIn("di luar DKI Jakarta", payload["content"])
        self.assertIn("BOGOR SELATAN", payload["content"])
        self.assertEqual(payload["slug"], "peringatan-dini-cuaca-jakarta-2026-11-22-pagi")
        self.assertEqual(pub.province_period_key(entry), pub.province_period_key(
            dict(entry, region="DKI Jakarta")))
        self.assertEqual(pub.province_day_key(entry), pub.province_day_key(
            dict(entry, url="https://www.bmkg.go.id/alerts/nowcast/id/CJK20261122002_alert.xml")))
        self.assertEqual(pub.province_day_key(entry), pub.province_day_key(
            dict(entry, region="DKI Jakarta")))

    def test_period_boundaries_and_local_bmkg_time(self):
        entry = example()
        cases = [
            ("2026-11-29T05:59:00+07:00", "2026-11-28", "Malam"),
            ("2026-11-29T06:00:00+07:00", "2026-11-29", "Pagi"),
            ("2026-11-29T11:59:00+07:00", "2026-11-29", "Pagi"),
            ("2026-11-29T12:00:00+07:00", "2026-11-29", "Siang"),
            ("2026-11-29T15:00:00+07:00", "2026-11-29", "Sore"),
            ("2026-11-29T18:00:00+07:00", "2026-11-29", "Malam"),
            ("2026-11-30T00:15:00+07:00", "2026-11-29", "Malam"),
            ("2026-11-29T06:00:00+09:00", "2026-11-29", "Pagi"),
        ]
        for issued, day, period in cases:
            with self.subTest(issued=issued):
                warning = dict(entry, issued=issued)
                self.assertEqual(pub.period_details(warning),
                                 (dt.date.fromisoformat(day), period))
                self.assertTrue(article(warning)["slug"].endswith(
                    f"{day}-{period.lower()}"))
        night = dict(entry, issued="2026-11-30T00:15:00+07:00")
        self.assertIn("29 November 2026 Malam", article(night)["title"])
        self.assertEqual(pub.province_period_key(night), pub.province_period_key(
            dict(entry, issued="2026-11-29T20:00:00+07:00")))

    def test_new_period_creates_new_post_and_second_warning_reuses_it(self):
        morning = example()
        noon = dict(morning, key="noon", identifier="NEW-NOON",
                    issued="2026-11-22T12:05:00+07:00",
                    effective="2026-11-22T12:10:00+07:00",
                    expires="2026-11-22T14:00:00+07:00")
        later = dict(noon, key="later", identifier="NEW-LATER",
                     issued="2026-11-22T12:30:00+07:00",
                     effective="2026-11-22T12:35:00+07:00")
        state = {"version": 1, "alerts": {}}
        wp = DummyWP()
        self.assertEqual(process([morning], "live",
            dt.datetime(2026, 11, 22, 4, 30, tzinfo=UTC), wp, state), 1)
        # Crossing noon alone does not create a new article.
        self.assertEqual(process([morning], "live",
            dt.datetime(2026, 11, 22, 5, 5, tzinfo=UTC), wp, state), 0)
        self.assertEqual(process([noon], "live",
            dt.datetime(2026, 11, 22, 5, 15, tzinfo=UTC), wp, state), 1)
        self.assertEqual(process([later], "live",
            dt.datetime(2026, 11, 22, 5, 45, tzinfo=UTC), wp, state), 1)
        self.assertEqual([call[1].get("post_id") for call in wp.calls],
                         [None, None, 124])
        self.assertEqual(len(state["province_periods"]), 2)
        self.assertEqual({p["post_id"] for p in state["province_periods"].values()},
                         {123, 124})
        self.assertEqual(wp.calls[-1][0]["content"].count("<li>"), 2)
        self.assertEqual(process([later], "live",
            dt.datetime(2026, 11, 22, 5, 50, tzinfo=UTC), wp, state), 0)

    def test_cap_revision_across_period_does_not_reuse_old_post(self):
        first = example()
        changed = dict(first, issued="2026-11-22T12:05:00+07:00",
                       effective="2026-11-22T12:10:00+07:00",
                       expires="2026-11-22T14:00:00+07:00",
                       description=first["description"] + " Kondisi terbaru.")
        state = {"version": 1, "alerts": {}}
        wp = DummyWP()
        process([first], "live", dt.datetime(2026, 11, 22, 4, 30, tzinfo=UTC), wp, state)
        process([changed], "live", dt.datetime(2026, 11, 22, 5, 15, tzinfo=UTC), wp, state)
        self.assertEqual(wp.calls[-1][1].get("post_id"), None)
        self.assertEqual({p["post_id"] for p in state["province_periods"].values()},
                         {123, 124})

    def test_midnight_warning_stays_in_previous_night_article(self):
        first = dict(example(), issued="2026-11-29T20:00:00+07:00",
                     effective="2026-11-29T20:05:00+07:00",
                     expires="2026-11-29T22:00:00+07:00")
        later = dict(first, key="after-midnight", identifier="AFTER-MIDNIGHT",
                     issued="2026-11-30T00:15:00+07:00",
                     effective="2026-11-30T00:20:00+07:00",
                     expires="2026-11-30T02:00:00+07:00")
        state = {"version": 1, "alerts": {}}
        wp = DummyWP()
        self.assertEqual(process([first], "live",
            dt.datetime(2026, 11, 29, 13, 30, tzinfo=UTC), wp, state), 1)
        self.assertEqual(process([later], "live",
            dt.datetime(2026, 11, 29, 17, 30, tzinfo=UTC), wp, state), 1)
        self.assertEqual(wp.calls[-1][1]["post_id"], 123)
        self.assertEqual(len(state["province_periods"]), 1)
        self.assertEqual(next(iter(state["province_periods"].values()))["day"],
                         "2026-11-29")
        self.assertIn("30 November 2026 pukul 00.15 WIB",
                      wp.calls[-1][0]["content"])

    def test_jabodetabek_update_reuses_bot_post_and_replaces_old_cover(self):
        entry = dict(example(), region="Jakarta",
                     url="https://www.bmkg.go.id/alerts/nowcast/id/CJK20261122001_alert.xml")
        wp = pub.WeatherWordPress("example", "not-a-secret")
        ledger = {"post_id": 123, "media_id": 456,
                  "last_wp_digest": pub.hash_value("bot article")}
        with (mock.patch.object(wp, "by_id", return_value={
                  "content": {"raw": "bot article"}, "featured_media": 456}),
              mock.patch.object(wp, "cover_image", return_value=789) as cover,
              mock.patch.object(pub.WordPress, "save", return_value={"post_id": 123}) as save):
            wp.save(article(entry), ledger, "publish", "dataloka-nowcast:old", entry)
        cover.assert_called_once_with(entry)
        self.assertEqual(save.call_args.args[0]["featured_media"], 789)

    def test_jabodetabek_update_does_not_replace_editor_cover(self):
        entry = dict(example(), region="Jakarta",
                     url="https://www.bmkg.go.id/alerts/nowcast/id/CJK20261122001_alert.xml")
        wp = pub.WeatherWordPress("example", "not-a-secret")
        ledger = {"post_id": 123, "media_id": 456,
                  "last_wp_digest": pub.hash_value("bot article")}
        with (mock.patch.object(wp, "by_id", return_value={
                  "content": {"raw": "editor article"}, "featured_media": 456}),
              mock.patch.object(wp, "cover_image") as cover,
              mock.patch.object(pub.WordPress, "save", return_value={"post_id": 123}) as save):
            wp.save(article(entry), ledger, "publish", "dataloka-nowcast:old", entry)
        cover.assert_not_called()
        self.assertNotIn("featured_media", save.call_args.args[0])

    def test_prepublish_rejects_missing_featured_image(self):
        wp = pub.WeatherWordPress("example", "not-a-secret")
        draft = {"status": "draft", "featured_media": 0, "tags": [7]}
        with (
            mock.patch.object(wp, "by_id", return_value=draft),
            mock.patch.object(pub.WordPress, "call") as write,
        ):
            with self.assertRaisesRegex(RuntimeError, "featured image missing"):
                wp.call("POST", "posts/123", payload={"status": "publish"})
            write.assert_not_called()

    def test_prepublish_allows_draft_without_featured_tag(self):
        wp = pub.WeatherWordPress("example", "not-a-secret")
        draft = {"status": "draft", "featured_media": 901, "tags": [3]}
        with (
            mock.patch.object(wp, "by_id", return_value=draft),
            mock.patch.object(pub.WordPress, "call", return_value={
                "id": 123, "status": "publish"}) as write,
            mock.patch.object(wp, "resolve_tags") as resolve,
        ):
            result = wp.call("POST", "posts/123", payload={"status": "publish"})
            self.assertEqual(result["status"], "publish")
            resolve.assert_not_called()
            write.assert_called_once_with(
                "POST", "posts/123", params=None, payload={"status": "publish"})

    def test_featured_cleanup_only_removes_term_from_bot_owned_post(self):
        wp = pub.WeatherWordPress("example", "not-a-secret")
        marker = "<!-- dataloka-nowcast:abc -->"
        content = "<p>Unchanged weather warning.</p>" + marker
        digest = pub.hash_value(content)
        post = {"id": 123, "content": {"raw": content}, "tags": [3, 7, 9]}
        verified = {"id": 123, "content": {"raw": content}, "tags": [3, 9]}
        with (
            mock.patch.object(wp, "by_id", side_effect=[post, verified]),
            mock.patch.object(pub.WordPress, "call", side_effect=[
                [{"id": 7, "name": "Featured", "slug": "featured"}],
                {"id": 123},
            ]) as call,
        ):
            self.assertTrue(wp.remove_featured_tag(123, marker, digest))
            call.assert_any_call("POST", "posts/123", params=None,
                                 payload={"tags": [3, 9]})

    def test_featured_cleanup_does_not_modify_human_edited_post(self):
        wp = pub.WeatherWordPress("example", "not-a-secret")
        marker = "<!-- dataloka-nowcast:abc -->"
        post = {"id": 123, "content": {"raw": "<p>Human edit</p>" + marker},
                "tags": [3, 7]}
        with (
            mock.patch.object(wp, "by_id", return_value=post),
            mock.patch.object(pub.WordPress, "call") as call,
        ):
            with self.assertRaises(pub.EditorialConflict):
                wp.remove_featured_tag(123, marker, "digest-from-ledger")
            call.assert_not_called()

    def test_tag_cleanup_does_not_republish_existing_unchanged_article(self):
        entry = example()
        state = {"version": 1, "alerts": {
            entry["key"]: {
                "post_id": 123,
                "fingerprint": fingerprint(entry),
                "editorial_version": pub.EDITORIAL_VERSION,
                "featured_tag_removed": False,
                "status": "publish",
            },
        }}
        wp = DummyWP()
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
        self.assertEqual(process([entry], "live", now, wp, state), 0)
        self.assertEqual(wp.calls, [])

    def test_featured_cleanup_marks_at_most_one_ledger_post(self):
        class RemoveWP:
            calls = []
            def remove_featured_tag(self, post_id, marker, digest):
                self.calls.append(post_id)
                return True
        wp = RemoveWP()
        ledger = {"version": 1, "alerts": {
            "first": {"post_id": 123, "last_wp_digest": "abc"},
            "second": {"post_id": 456, "last_wp_digest": "xyz"},
        }}
        self.assertEqual(pub.cleanup_existing_featured(wp, state=ledger), 1)
        self.assertEqual(wp.calls, [123])
        self.assertTrue(ledger["alerts"]["first"]["featured_tag_removed"])
        self.assertNotIn("featured_tag_removed", ledger["alerts"]["second"])

    def test_timeout_draft_post_recovers_only_identical_slug_and_content(self):
        wp = pub.WeatherWordPress("example", "not-a-secret")
        entry = example()
        payload = article(entry)
        draft = {
            "id": 321, "status": "draft",
            "slug": payload["slug"],
            "content": {"raw": payload["content"]},
        }
        with (
            mock.patch.object(pub.WordPress, "call", side_effect=RuntimeError(
                "WordPress network error on POST posts: TimeoutError")),
            mock.patch.object(wp, "by_slug", return_value=draft) as lookup,
        ):
            self.assertEqual(
                wp.call("POST", "posts", payload={
                    "status": "draft",
                    "slug": payload["slug"],
                    "content": payload["content"],
                })["id"], 321)
            lookup.assert_called_once_with(payload["slug"])

    def test_timeout_draft_post_rejects_unrelated_existing_content(self):
        wp = pub.WeatherWordPress("example", "not-a-secret")
        entry = example()
        payload = article(entry)
        draft = {
            "id": 321, "status": "draft",
            "slug": payload["slug"],
            "content": {"raw": "unrelated article"},
        }
        with (
            mock.patch.object(pub.WordPress, "call", side_effect=RuntimeError(
                "WordPress network error on POST posts: TimeoutError")),
            mock.patch.object(wp, "by_slug", return_value=draft),
        ):
            with self.assertRaisesRegex(RuntimeError, "network error on POST posts"):
                wp.call("POST", "posts", payload={
                    "status": "draft",
                    "slug": payload["slug"],
                    "content": payload["content"],
                })

    def test_five_regions_then_resume_older_active_warning(self):
        first = example()
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
        entries = [dict(first, key=str(i), identifier=f"warning{i}", region=region,
                        issued=(now - dt.timedelta(minutes=100)).isoformat())
                   for i, region in enumerate(["Bali", "Bali", "Jawa Barat",
                                               "Aceh", "Sumatera Barat", "Kalimantan Utara", "Bengkulu"])]
        state = {"version": 1, "alerts": {}}
        wp = DummyWP()
        self.assertEqual(process(entries, "live", now, wp, state), 5)
        self.assertEqual(len(set(call[0]["title"] for call in wp.calls)), 5)
        self.assertEqual(len({pub.province_period_key(item)
                              for item in state["pending"].values()}), 1)
        self.assertEqual(process(entries, "live", now, wp, state), 1)
        self.assertEqual(process(entries, "live", now, wp, state), 0)
        self.assertEqual(len(wp.calls), 6)
        bali = [call for call in wp.calls if "Cuaca Bali" in call[0]["title"]]
        self.assertEqual(len(bali), 1)
        self.assertEqual(bali[0][0]["content"].count("<li>"), 2)

    def test_cancelled_and_withdrawn_queue_entries(self):
        first = example()
        second = dict(first, key="second", identifier="other")
        state = {"version": 1, "alerts": {}}
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
        pub.collect([first, second], state, now)
        pub.collect([first], state, now, cancelled={first["identifier"]})
        self.assertFalse(state["pending"])
        self.assertEqual(state["skipped"][first["key"]]["reason"], "cancelled")
        self.assertEqual(state["skipped"]["second"]["reason"], "withdrawn")

    def test_wordpress_timeout_stops_following_alerts(self):
        first = example()
        second = dict(first, key="1234567890abcdef", identifier="ANOTHER")
        state = {"version": 1, "alerts": {}}
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
        class FailWP:
            calls = 0
            def save(self, *args, **kwargs):
                self.calls += 1
                raise RuntimeError("WordPress network error on POST posts: TimeoutError")
        wp = FailWP()
        with self.assertRaisesRegex(RuntimeError, "Failed live weather alerts"):
            process([first, second], "live", now, wp, state)
        self.assertEqual(wp.calls, 1)

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

    def test_second_provincial_warning_updates_first_article(self):
        first = example()
        second = dict(first, key="another-cap", identifier="ANOTHER",
                      url="https://www.bmkg.go.id/alerts/nowcast/id/CJB20261122002_alert.xml",
                      issued="2026-11-22T11:30:00+07:00",
                      effective="2026-11-22T11:35:00+07:00")
        state = {"version": 1, "alerts": {}}
        wp = DummyWP()
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
        self.assertEqual(process([first], "live", now, wp, state), 1)
        self.assertEqual(process([second], "live", now, wp, state), 1)
        self.assertEqual(len(wp.calls), 2)
        self.assertEqual(wp.calls[1][1]["post_id"], 123)
        self.assertEqual(wp.calls[1][0]["content"].count("<li>"), 2)
        self.assertLess(wp.calls[1][0]["content"].index("11.35 WIB hingga"),
                        wp.calls[1][0]["content"].index("11.05 WIB hingga"))

    def test_changed_event_accepts_previous_bot_headline(self):
        first = example()
        second = dict(first, key="new-event", identifier="NEW-EVENT",
                      event="Angin Kencang",
                      issued="2026-11-22T11:30:00+07:00")
        state = {"version": 1, "alerts": {}}
        wp = DummyWP()
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
        process([first], "live", now, wp, state)
        process([second], "live", now, wp, state)
        self.assertEqual(wp.calls[-1][1]["post_id"], 123)
        self.assertIn("BMKG: Peringatan Hujan Lebat dan Petir di Jawa Barat",
                      wp.calls[-1][1]["bot_previous_titles"])

    def test_jabodetabek_existing_period_article_accepts_previous_bot_title(self):
        first = dict(example(), region="Jakarta",
                     url="https://www.bmkg.go.id/alerts/nowcast/id/CJK20261122001_alert.xml")
        next_warning = dict(first, key="second-cjk", identifier="ANOTHER",
                            issued="2026-11-22T11:30:00+07:00")
        state = {"version": 1, "alerts": {}}
        wp = DummyWP()
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
        process([first], "live", now, wp, state)
        process([next_warning], "live", now, wp, state)
        self.assertEqual(wp.calls[-1][1]["post_id"], 123)
        self.assertIn("BMKG: Peringatan Hujan Lebat dan Petir di Jakarta",
                      wp.calls[-1][1]["bot_previous_titles"])

    def test_rollout_does_not_republish_existing_daily_article(self):
        entry = example()
        old = {
            "post_id": 123, "status": "publish",
            "fingerprint": fingerprint(entry),
            "editorial_version": 3,
            "last_wp_digest": "last-bot-written-content",
        }
        old_key = pub.province_day_key(entry)
        state = {"version": 1, "alerts": {entry["key"]: old},
                 "province_days": {old_key: dict(old, region=entry["region"])}}
        wp = DummyWP()
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC)
        self.assertEqual(process([entry], "live", now, wp, state), 0)
        self.assertFalse(wp.calls)
        self.assertFalse(state["province_periods"])
        self.assertEqual(state["province_days"][old_key]["post_id"], 123)

    def test_new_alert_does_not_overwrite_legacy_daily_post(self):
        old = example()
        fresh = dict(old, key="new-cap", identifier="NEW-CAP",
                     issued="2026-11-22T11:30:00+07:00",
                     effective="2026-11-22T11:35:00+07:00")
        daily = {"post_id": 900, "fingerprint": fingerprint(old),
                 "editorial_version": 3}
        daily_key = pub.province_day_key(old)
        state = {"version": 1, "alerts": {old["key"]: daily},
                 "province_days": {daily_key: dict(daily, region=old["region"])}}
        wp = DummyWP()
        self.assertEqual(process([old, fresh], "live",
            dt.datetime(2026, 11, 22, 5, 0, tzinfo=UTC), wp, state), 1)
        self.assertFalse(wp.calls[0][1].get("post_id"))
        self.assertEqual(state["province_days"][daily_key]["post_id"], 900)
        self.assertEqual(len(state["province_periods"]), 1)

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
