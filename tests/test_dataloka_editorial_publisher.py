import importlib.util
import contextlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location(
    "publisher", Path(__file__).resolve().parents[1] /
    "scripts" / "dataloka_editorial_publisher.py"
)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def valid():
    return {
        "request_id": "tes-artikel-publik-20261117",
        "site": "dataloka.id",
        "operation": "publish",
        "title": "Tren Curah Hujan di Indonesia Berdasarkan BMKG 2026",
        "slug": "tren-curah-hujan-indonesia-bmkg-2026",
        "summary": "Ulasan data BMKG tentang curah hujan dalam sejumlah wilayah Indonesia sepanjang November 2026.",
        "content_html": "<p>Data hujan dari BMKG memperlihatkan perbedaan kondisi di sejumlah provinsi Indonesia.</p><p>Angka berasal dari laporan BMKG yang telah dihimpun dan diverifikasi oleh redaksi.</p>",
        "category_slug": "berita",
        "tags": ["BMKG", "Hujan"],
        "seo": {
            "focus_keyphrase": "curah hujan Indonesia 2026",
            "seo_title": "Curah Hujan Indonesia 2026 Menurut BMKG",
            "meta_description": "Analisis data hujan BMKG sepanjang November 2026, wilayah yang dilanda curah hujan tinggi dan perbandingan provinsi.",
        },
    }


class PublisherTests(unittest.TestCase):
    def validated(self, data=None):
        return p.validate_request(data or valid(), "publisher/outbox/tes-artikel-publik-20261117.json")

    def test_public_repo_only_supports_publish_to_dataloka(self):
        req = self.validated()
        self.assertEqual(p.WP_BASE, "https://dataloka.id/wp-json/wp/v2")
        self.assertEqual(req["slug"], "tren-curah-hujan-indonesia-bmkg-2026")
        self.assertIn("dataloka-editorial:tes-artikel-publik-20261117:", req["marker"])
        for key, value in [
            ("site", "pirsadata.id"),
            ("operation", "draft"),
            ("operation", "update"),
        ]:
            bad = valid()
            bad[key] = value
            with self.assertRaises(ValueError):
                self.validated(bad)

    def test_filename_and_request_id_must_match(self):
        bad = valid()
        bad["request_id"] = "artikel-yang-lain"
        with self.assertRaises(ValueError):
            self.validated(bad)
        bad = valid()
        bad["content_html"] += "<!-- dataloka-editorial:someone -->"
        with self.assertRaises(ValueError):
            self.validated(bad)

    def test_enforces_summary_seo_and_tag_limits(self):
        bad = valid()
        bad["summary"] = "x" * 301
        with self.assertRaises(ValueError):
            self.validated(bad)
        bad = valid()
        bad["seo"]["meta_description"] = "x" * 161
        with self.assertRaises(ValueError):
            self.validated(bad)
        bad = valid()
        bad["tags"] = [f"tag-{i}" for i in range(9)]
        with self.assertRaises(ValueError):
            self.validated(bad)

    def test_publish_new_with_verified_yoast_before_publication(self):
        req = self.validated()
        class WP:
            def __init__(self):
                self.status = "draft"
                self.actions = []
            def find_slug(self, slug):
                return []
            def category_id(self, slug):
                self.actions.append(("category", slug))
                return 43
            def resolve_tags(self, tags):
                self.actions.append(("tags", tags))
                return [10, 11]
            def call(self, method, route, params=None, payload=None):
                self.actions.append((method, route, payload))
                if route == "posts":
                    self.payload = payload
                    return {"id": 9050}
                if route == "posts/9050":
                    self.status = payload["status"]
                    return {"id": 9050}
                raise AssertionError(route)
            def get_post(self, post_id):
                return {
                    "id": 9050, "slug": req["slug"],
                    "status": self.status,
                    "content": {"raw": req["content"]},
                    "meta": req["meta"],
                }
        wp = WP()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(p.publish_one(wp, req), 9050)
        self.assertEqual(wp.payload["status"], "draft")
        self.assertEqual(wp.payload["categories"], [43])
        self.assertEqual(wp.payload["tags"], [10, 11])
        self.assertEqual(wp.payload["meta"], req["meta"])
        self.assertEqual(wp.status, "publish")
        self.assertEqual(len([a for a in wp.actions
                              if len(a) > 1 and a[1] == "posts/9050"]), 1)

    def test_unrelated_post_with_same_slug_is_never_overwritten(self):
        req = self.validated()
        class WP:
            def find_slug(self, slug):
                return [{"id": 995}]
            def get_post(self, post_id):
                return {
                    "slug": req["slug"], "status": "publish",
                    "content": {"raw": "<p>Human editor content</p>"},
                    "meta": req["meta"],
                }
        with self.assertRaisesRegex(RuntimeError, "ownership marker"):
            p.publish_one(WP(), req)

    def test_incomplete_yoast_blocks_publication(self):
        req = self.validated()
        class WP:
            def find_slug(self, slug):
                return []
            def category_id(self, slug):
                return 43
            def resolve_tags(self, tags):
                return []
            def call(self, method, route, params=None, payload=None):
                if route == "posts":
                    self.creation = payload
                    return {"id": 901}
                self.published = True
                return {"id": 901}
            def get_post(self, post_id):
                return {
                    "slug": req["slug"], "status": "draft",
                    "content": {"raw": req["content"]},
                    "meta": {},
                }
        wp = WP()
        with self.assertRaisesRegex(RuntimeError, "Yoast"):
            p.publish_one(wp, req)
        self.assertEqual(wp.creation["status"], "draft")
        self.assertFalse(getattr(wp, "published", False))

    def test_newly_added_only_and_filename_safety(self):
        before, after = "a" * 40, "b" * 40
        with mock.patch.object(subprocess, "check_output",
                               return_value=b"publisher/outbox/good-name.json\0"):
            names = p.newly_added(before, after)
            self.assertEqual(names, ["publisher/outbox/good-name.json"])
        with mock.patch.object(subprocess, "check_output",
                               return_value=b"publisher/outbox/../payload.json\0"):
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                p.newly_added(before, after)
        self.assertEqual(p.newly_added("0" * 40, after), [])


if __name__ == "__main__":
    unittest.main()
