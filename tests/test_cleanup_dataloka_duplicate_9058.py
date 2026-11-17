import importlib.util
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "duplicate_cleanup", ROOT / "scripts" / "cleanup_dataloka_duplicate_9058.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CleanupTests(unittest.TestCase):
    def wp(self, *, state="draft", body=None):
        class WP:
            def __init__(self):
                self.calls = []
            def by_id(self, post_id):
                self.calls.append(("GET", post_id))
                if post_id == m.ORIGINAL_ID:
                    return {"id": post_id, "status": "draft"}
                return {"id": post_id, "status": state,
                        "content": {"raw": body if body is not None else (
                            "<p>A verified bot draft.</p>" + m.EVENT_MARKER)}}
            def call(self, method, route, params=None, payload=None):
                self.calls.append((method, route, params))
                return {"id": m.ACCIDENTAL_ID, "status": "trash"}
        return WP()

    def test_only_verified_duplicate_goes_to_reversible_trash(self):
        wp = self.wp()
        with mock.patch.object(m, "hash_value",
                               return_value=m.ACCIDENTAL_DIGEST):
            m.cleanup(wp)
        self.assertEqual(wp.calls, [
            ("GET", 9058), ("GET", 9041),
            ("DELETE", "posts/9058", {"force": "false"})])

    def test_human_edited_copy_must_be_left_untouched(self):
        wp = self.wp()
        with mock.patch.object(m, "hash_value", return_value="modified"):
            with self.assertRaisesRegex(RuntimeError, "edited"):
                m.cleanup(wp)
        self.assertEqual(wp.calls, [("GET", 9058)])

    def test_missing_marker_prevents_delete(self):
        wp = self.wp(body="<p>This draft belongs to an editor</p>")
        with self.assertRaisesRegex(RuntimeError, "ownership"):
            m.cleanup(wp)
        self.assertEqual(wp.calls, [("GET", 9058)])

    def test_published_article_never_deleted(self):
        wp = self.wp(state="publish")
        with self.assertRaisesRegex(RuntimeError, "modified or published"):
            m.cleanup(wp)
        self.assertEqual(wp.calls, [("GET", 9058)])

    def test_idempotent_if_already_trashed(self):
        wp = self.wp(state="trash")
        m.cleanup(wp)
        self.assertEqual(wp.calls, [("GET", 9058)])


if __name__ == "__main__":
    unittest.main()
