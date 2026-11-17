import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "seo_only9057", ROOT / "scripts" / "update_dataloka_9057_seo_only.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

from scripts import dataloka_wp_gempa as p


class SEOOnlyUpdateTests(unittest.TestCase):
    def setUp(self):
        self.event = p.normalize({
            "DateTime": "2026-11-17T00:49:17+00:00",
            "Coordinates": "-8.22,120.66",
            "Magnitude": "4.8",
            "Kedalaman": "2 km",
            "Wilayah": "Pusat gempa berada di laut 49 km timur laut Ruteng, Manggarai",
            "Dirasakan": "III Kab. Manggarai",
        }, "gempadirasakan.json")
        self.event["key"] = m.EVENT_KEY
        self.old_meta = {
            "_yoast_wpseo_focuskw":
                "gempa M4,8 di Pusat gempa berada di laut 49 km timur laut Ruteng, Manggarai",
            "_yoast_wpseo_title": p.seo_title(self.event, "17 November 2026"),
            "_yoast_wpseo_metadesc":
                "Gempa M4,8 di lokasi pusat gempa lama pada 17 November 2026.",
        }
        self.state = {"version": 1, "daily": {}, "events": [{
            "key": m.EVENT_KEY,
            "data": self.event,
            "post_id": m.POST_ID,
            "yoast_meta_digest": p.hash_value(json.dumps(
                self.old_meta, ensure_ascii=False, sort_keys=True)),
        }]}

    def fake_wp(self, *, seo_modified=False, marker_present=True,
                status="draft"):
        test = self
        class WP:
            def __init__(self):
                self.meta = dict(test.old_meta)
                if seo_modified:
                    self.meta["_yoast_wpseo_focuskw"] = "Kata kunci hasil suntingan redaksi"
                self.writes = []
            def by_id(self, post_id):
                return {
                    "id": post_id,
                    "status": status,
                    "title": {"raw": "Judul khusus yang diedit editor"},
                    "content": {"raw": "<p>Isi diubah redaksi.</p>" + (
                        m.MARKER if marker_present else ""
                    )},
                    "featured_media": 9060,
                    "slug": "custom-slug-keputusan-redaksi",
                    "meta": dict(self.meta),
                }
            def call(self, method, route, params=None, payload=None):
                self.writes.append((method, route, payload))
                self.meta.update(payload["meta"])
                return {"id": m.POST_ID}
            _verified_yoast = staticmethod(p.WordPress._verified_yoast)
        return WP()

    def test_updates_only_two_yoast_keys_no_editorial_fields(self):
        wp = self.fake_wp()
        m.reconcile(wp, self.state)
        self.assertEqual(len(wp.writes), 1)
        method, route, payload = wp.writes[0]
        self.assertEqual((method, route), ("POST", "posts/9057"))
        self.assertEqual(set(payload), {"meta"})
        self.assertEqual(set(payload["meta"]), set(m.EDITABLE_KEYS))
        self.assertEqual(
            wp.meta["_yoast_wpseo_focuskw"],
            "gempa M4.8 di Ruteng Manggarai",
        )
        self.assertEqual(
            wp.meta["_yoast_wpseo_metadesc"],
            "Pusat gempa M4,8 berada di laut 49 km timur laut Ruteng, "
            "Manggarai pada 17 November 2026, pukul 07.49 WIB. "
            "Simak informasi resmi BMKG.",
        )
        self.assertEqual(wp.meta["_yoast_wpseo_title"],
                         self.old_meta["_yoast_wpseo_title"])

    def test_explicitly_requested_fields_can_replace_previous_editor_seo(self):
        wp = self.fake_wp(seo_modified=True)
        wp.meta["_yoast_wpseo_title"] = "Judul SEO yang telah diubah editor"
        m.reconcile(wp, self.state)
        self.assertEqual(len(wp.writes), 1)
        self.assertEqual(
            wp.meta["_yoast_wpseo_focuskw"], "gempa M4.8 di Ruteng Manggarai")
        self.assertEqual(wp.meta["_yoast_wpseo_title"],
                         "Judul SEO yang telah diubah editor")
        self.assertEqual(set(wp.writes[0][2]["meta"]), set(m.EDITABLE_KEYS))

    def test_missing_bot_marker_blocks_update(self):
        wp = self.fake_wp(marker_present=False)
        with self.assertRaisesRegex(RuntimeError, "ownership marker"):
            m.reconcile(wp, self.state)
        self.assertEqual(wp.writes, [])

    def test_published_article_blocks_update(self):
        wp = self.fake_wp(status="publish")
        with self.assertRaisesRegex(RuntimeError, "not the expected WordPress draft"):
            m.reconcile(wp, self.state)
        self.assertEqual(wp.writes, [])

    def test_wrong_event_or_post_mapping_blocks_update(self):
        wp = self.fake_wp()
        with self.assertRaisesRegex(RuntimeError, "not in publisher ledger"):
            m.reconcile(wp, {"events": []})
        self.assertEqual(wp.writes, [])

    def test_second_run_is_idempotent(self):
        wp = self.fake_wp()
        m.reconcile(wp, self.state)
        m.reconcile(wp, self.state)
        self.assertEqual(len(wp.writes), 1)


if __name__ == "__main__":
    unittest.main()
