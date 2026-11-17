"""Tests for a strictly one-time editorial correction. No live HTTP calls."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "revision", Path(__file__).resolve().parents[1] / "scripts" / "revise_dataloka_9044.py")
revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revision)

BODY = (
    "<p>Dataloka.id – Gempa bumi berkekuatan magnitudo 7,1 mengguncang "
    "wilayah barat daya Maluku Tenggara. Berdasarkan laporan BMKG, gempa "
    "tersebut tidak berpotensi tsunami.</p>"
    "<p>BMKG menyebut koordinat 6,03 derajat lintang selatan dan "
    "131,62 derajat bujur timur. Lokasi 130 kilometer di barat daya "
    "Maluku Tenggara, pada kedalaman 115 kilometer.</p>"
    "<h3>Wilayah yang Merasakan Gempa Maluku M7,1</h3>"
    "<table><tr><td>Saumlaki</td><td>III MMI</td></tr></table>"
    "<p>Informasi dapat diperbarui. (RK/D-1)</p>"
)

class RevisionTests(unittest.TestCase):
    def post(self, **kwargs):
        post = {
            "id": 9044, "status": "publish", "slug": "gempa-m71-maluku-tenggara",
            "title": {"raw": "Gempa M7,1 Maluku Tenggara Terasa di 12 Wilayah"},
            "content": {"raw": BODY},
            "excerpt": {"raw": "Gempa M7,1 di Maluku Tenggara"},
            "meta": {
                "_yoast_wpseo_title": "Gempa M7,1 di Maluku Tenggara",
                "_yoast_wpseo_metadesc": "Gempa M7,1 di Maluku Tenggara",
                "_yoast_wpseo_focuskw": "Gempa M7,1 Maluku",
            },
        }
        post.update(kwargs)
        return post

    def test_updates_parameters_and_preserves_table_and_credit(self):
        updated = revision.build_payload(self.post())
        body = updated["content"]
        self.assertIn("M6,8", updated["title"])
        self.assertIn("97 kilometer", body)
        self.assertIn("6,12 derajat lintang selatan", body)
        self.assertIn("131,63 derajat bujur timur", body)
        self.assertIn("132 kilometer di barat daya", body)
        self.assertIn("115 kilometer menjadi", body)
        self.assertIn("M7,1 menjadi", body)
        self.assertIn("Saumlaki</td><td>III MMI", body)
        self.assertIn("(RK/D-1)", body)
        self.assertEqual(body.count(revision.MARKER), 1)
        self.assertIn("M6,8", updated["excerpt"])
        self.assertIn("M6,8", updated["meta"]["_yoast_wpseo_title"])
        self.assertNotIn("slug", updated)
        self.assertNotIn("status", updated)

    def test_no_duplicate_revision(self):
        existing = BODY + revision.REVISION_NOTE
        self.assertIsNone(revision.build_payload(self.post(content={"raw": existing})))

    def test_cannot_change_another_post(self):
        with self.assertRaisesRegex(ValueError, "Incorrect WordPress post ID"):
            revision.build_payload(self.post(id=9045))

    def test_cannot_change_draft(self):
        with self.assertRaisesRegex(ValueError, "not currently published"):
            revision.build_payload(self.post(status="draft"))

    def test_unexpected_existing_edit_is_not_replaced(self):
        with self.assertRaisesRegex(ValueError, "Original earthquake parameters"):
            revision.revise_html(BODY.replace("115 kilometer", "150 kilometer"))

if __name__ == "__main__":
    unittest.main()
