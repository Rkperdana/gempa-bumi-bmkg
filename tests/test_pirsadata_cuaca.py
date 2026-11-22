#!/usr/bin/env python3
"""Offline contract tests for the new, isolated Pirsadata weather publisher."""
import base64
import datetime as dt
import io
import json
from email.message import Message
from pathlib import Path
import sys
import unittest
from unittest import mock
import urllib.error
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import pirsadata_cuaca as p

SOURCE = "https://www.bmkg.go.id/alerts/nowcast/id/CJB20251013001_alert.xml"
ENDPOINT = "https://pirsadata.perdanark.chatgpt.site/api/integrations/bmkg/weather"
TOPIC = "https://pirsadata.perdanark.chatgpt.site/tag/cuaca"
FIXTURE = ROOT / "tests" / "fixtures" / "nowcast-sample.xml"


def example():
    return p.parse_cap(FIXTURE.read_bytes(), SOURCE)


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(json.dumps(body).encode("utf-8"))
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"


class Capture:
    def __init__(self, result=None, exception=None):
        self.requests = []
        self.result = result or {
            "ok": True,
            "policy": {"version": p.POLICY},
            "result": {
                "alertId": example()["key"],
                "postId": 301,
                "featuredImageId": 900,
                "status": "publish",
                "tags": ["Featured", "Cuaca"],
            },
        }
        self.exception = exception

    def open(self, request, timeout):
        self.requests.append(request)
        if self.exception:
            raise self.exception
        return Response(self.result)


class WeatherTests(unittest.TestCase):
    def test_five_paragraphs_plus_separate_source_credit(self):
        item = p.article(example(), TOPIC)
        parts = item["contentHtml"].split("<p>")
        self.assertEqual(item["contentHtml"].count("<p>"), 6)
        self.assertEqual(item["contentHtml"].count("</p>"), 6)
        self.assertEqual(len(parts), 7)
        self.assertIn('href="' + TOPIC + '">cuaca</a>', parts[1])
        self.assertIn("\n<p><strong>Sumber:</strong>", item["contentHtml"])
        self.assertIn(SOURCE, item["contentHtml"])
        self.assertNotIn("dataloka.id", item["contentHtml"].lower())
        self.assertEqual(item["tags"].count("Featured"), 1)
        self.assertEqual(item["category"], "Lingkungan")
        self.assertLessEqual(len(item["summary"]), 280)
        self.assertIn("peringatan dini cuaca", item["focusKeyphrase"])

    def test_link_is_optional_until_pirsadata_topic_route_exists(self):
        item = p.article(example())
        self.assertNotIn("dataloka", item["contentHtml"].lower())
        self.assertIn("dini cuaca terkait", item["contentHtml"])
        with self.assertRaises(ValueError):
            p.article(example(), "https://dataloka.id/tag/cuaca")

    def test_cover_is_original_pirsadata_jpeg(self):
        item = p.build_item(example(), TOPIC)
        image = base64.b64decode(item["featuredImage"]["dataBase64"])
        self.assertLess(len(image), 500_000)
        im = Image.open(io.BytesIO(image))
        self.assertEqual(im.size, (1200, 675))
        self.assertEqual(im.format, "JPEG")
        self.assertTrue(item["featuredImage"]["filename"].startswith("pirsadata-cuaca"))
        self.assertEqual(item["sourceUrl"], SOURCE)

    def test_rejects_earthquake_endpoint_and_external_urls(self):
        for endpoint in (
            "https://pirsadata.perdanark.chatgpt.site/api/integrations/bmkg/earthquakes",
            "https://pirsadata.perdanark.chatgpt.site/api/integrations/bmkg/ingest",
            "https://dataloka.id/api/integrations/bmkg/weather",
            "http://pirsadata.perdanark.chatgpt.site/api/integrations/bmkg/weather",
            "https://pirsadata.perdanark.chatgpt.site/api/integrations/bmkg/weather?secret=1",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    p.site_url(endpoint, integration=True)

    def test_receipt_and_idempotency_contract(self):
        item = p.build_item(example(), TOPIC)
        capture = Capture()
        result = p.send(item, endpoint=ENDPOINT, token="separate-weather-token",
                        sites_token="sites-token", opener=capture)
        self.assertEqual(result["postId"], 301)
        self.assertEqual(len(capture.requests), 1)
        req = capture.requests[0]
        self.assertEqual(req.full_url, ENDPOINT)
        self.assertEqual(req.get_header("Authorization"),
                         "Bearer separate-weather-token")
        self.assertEqual(req.get_header("Oai-sites-authorization"), "Bearer sites-token")
        self.assertTrue(req.get_header("X-pirsadata-idempotency-key"))
        sent = json.loads(req.data)
        self.assertEqual(sent["alert"]["alertId"], item["alertId"])
        self.assertEqual(sent["alert"]["featuredImage"]["mimeType"], "image/jpeg")
        self.assertIn("Featured", sent["alert"]["tags"])

    def test_declines_unverified_publish_receipt(self):
        item = p.build_item(example())
        for tamper in (
            {"ok": True, "policy": {"version": "other"},
             "result": Capture().result["result"]},
            {"ok": True, "policy": {"version": p.POLICY},
             "result": {**Capture().result["result"], "featuredImageId": 0}},
            {"ok": True, "policy": {"version": p.POLICY},
             "result": {**Capture().result["result"], "tags": ["Cuaca"]}},
        ):
            with self.subTest(tamper=tamper):
                with self.assertRaises(RuntimeError):
                    p.send(item, endpoint=ENDPOINT, token="x", sites_token="y",
                           opener=Capture(result=tamper))

    def test_timeout_is_not_retried(self):
        item = p.build_item(example())
        capture = Capture(exception=TimeoutError("WP unavailable"))
        with self.assertRaisesRegex(RuntimeError, "outcome uncertain"):
            p.send(item, endpoint=ENDPOINT, token="x", sites_token="y",
                   opener=capture)
        self.assertEqual(len(capture.requests), 1)

    def test_dry_run_cannot_send(self):
        state = {"version": 1, "alerts": {}}
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=p.UTC)
        def forbidden(_):
            raise AssertionError("dry run accessed Pirsadata CMS")
        self.assertEqual(p.process([example()], "dry-run", now=now,
                                   state=state, publisher=forbidden), 1)
        self.assertFalse(state["alerts"])

    def test_live_receipt_deduplicates_and_updates(self):
        item = example()
        state = {"version": 1, "alerts": {}}
        now = dt.datetime(2026, 11, 22, 5, 0, tzinfo=p.UTC)
        saved = []
        def publisher(payload):
            saved.append(payload)
            return {"postId": 301, "featuredImageId": 900, "status": "publish"}
        self.assertEqual(p.process([item], "live", now=now, state=state,
                                   publisher=publisher), 1)
        self.assertEqual(p.process([item], "live", now=now, state=state,
                                   publisher=publisher), 0)
        amended = dict(item, description=item["description"] + " Revisi BMKG.")
        self.assertEqual(p.process([amended], "live", now=now, state=state,
                                   publisher=publisher), 1)
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]["alertId"], saved[1]["alertId"])
        self.assertEqual(state["alerts"][item["key"]]["postId"], 301)

    def test_expired_alert_not_sent(self):
        now = dt.datetime(2026, 11, 22, 7, 0, tzinfo=p.UTC)
        with mock.patch.object(p, "send", side_effect=AssertionError("sent")):
            self.assertEqual(p.process([example()], "dry-run", now=now,
                                       state={"version": 1, "alerts": {}}), 0)

    def test_at_most_one_per_run(self):
        one = example()
        two = {**one, "key": "abc" * 5 + "x", "identifier": "other"}
        count = p.process([one, two], "dry-run",
                          now=dt.datetime(2026, 11, 22, 5, 0, tzinfo=p.UTC),
                          state={"version": 1, "alerts": {}})
        self.assertEqual(count, 1)

    def test_no_redirect_of_credentials(self):
        self.assertIsNone(
            p.NoRedirect().redirect_request(None, None, 302, "", {},
                                            "https://outside.invalid")
        )


if __name__ == "__main__":
    unittest.main()
