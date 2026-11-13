import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import unittest
import urllib.error
from email.message import Message

spec = importlib.util.spec_from_file_location('sender', Path(__file__).parents[1] / 'scripts/send_lensadata.py')
sender = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sender)
NOW = dt.datetime(2026, 11, 13, 1, tzinfo=dt.timezone.utc)
EVENT = {'id': 'real-event', 'datetime': '2026-11-13T00:05:10Z', 'magnitude': 5.5, 'depth_km': 91, 'lat': 34.75, 'lon': 24.97, 'region': 'Crete, Greece', 'felt': False, 'felt_info': '', 'potential_text': '', 'source_urls': ['https://www.bmkg.go.id/gempabumi/gempabumi-realtime']}
CONFIG = {'ingest_token':'test-ingest','sites_token':'test-site','run_id':'123','run_attempt':'1'}


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(json.dumps(data).encode())
        self.headers = Message()
        self.headers['Content-Type'] = 'application/json'


class Opener:
    def __init__(self, failures=0, code=503):
        self.requests = []
        self.failures = failures
        self.code = code

    def open(self, request, timeout):
        self.requests.append(request)
        if self.failures:
            self.failures -= 1
            raise urllib.error.HTTPError(request.full_url, self.code, 'error', {}, None)
        return Response({'ok':True,'result':{'rejected':0,'published':1},'policy':{'version':sender.EXPECTED_POLICY}})


class SenderTests(unittest.TestCase):
    def test_mapping_and_no_invented_tsunami_status(self):
        rows = sender.select_events({'status':'live','events':[EVENT, EVENT]}, now=NOW)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['magnitude'],5.5)
        self.assertEqual(rows[0]['potentialText'],'')
        self.assertEqual(rows[0]['sourceUrl'],EVENT['source_urls'][0])

    def test_historical_cutoff_and_felt_selection(self):
        old = {**EVENT,'id':'old','datetime':'2026-11-09T00:00:00Z'}
        small = {**EVENT,'id':'small','magnitude':4.2}
        felt = {**small,'id':'felt','felt_info':'III Sumbawa'}
        rows = sender.select_events({'status':'live','events':[old,small,felt]}, now=NOW)
        self.assertEqual([row['eventId'] for row in rows],['felt'])

    def test_history_includes_small_events_without_publishing_them(self):
        small = {**EVENT,'id':'context-only','magnitude':2.5}
        snapshot = {'status':'live','events':[EVENT,small]}
        self.assertEqual(len(sender.select_events(snapshot,now=NOW)),1)
        self.assertEqual(len(sender.select_events(snapshot,now=NOW,include_context=True)),2)
        opener=Opener()
        sender.send_events([{'eventId':'main'}],CONFIG,opener=opener,history=[{'eventId':str(i)} for i in range(230)])
        payload=json.loads(opener.requests[0].data)
        self.assertEqual(len(payload['history']),200)
        self.assertEqual(payload['events'],[{'eventId':'main'}])

    def test_preview_and_invalid_data_rejected(self):
        for snapshot in [{'status':'preview','events':[EVENT]}, {'status':'live','events':[{**EVENT,'magnitude':float('nan')}]}, {'status':'live','events':[{**EVENT,'datetime':'2030-01-01T00:00:00Z'}]}]:
            with self.assertRaises(ValueError): sender.select_events(snapshot,now=NOW)

    def test_batches_have_different_idempotency_keys(self):
        opener=Opener()
        sender.send_events([{'eventId':str(i)} for i in range(51)],CONFIG,opener=opener)
        self.assertEqual(len(opener.requests),2)
        self.assertNotEqual(opener.requests[0].get_header('X-lensadata-batch'),opener.requests[1].get_header('X-lensadata-batch'))
        self.assertEqual(opener.requests[0].full_url,sender.ENDPOINT)
        self.assertEqual(opener.requests[0].get_header('Authorization'),'Bearer test-ingest')
        self.assertEqual(opener.requests[0].get_header('Oai-sites-authorization'),'Bearer test-site')

    def test_retry_preserves_request_and_dry_run(self):
        opener=Opener(failures=1)
        sender.send_events([{'eventId':'one'}],CONFIG,dry_run=True,opener=opener,sleeper=lambda _:None)
        self.assertEqual(len(opener.requests),2)
        self.assertEqual(opener.requests[0].headers,opener.requests[1].headers)
        self.assertEqual(opener.requests[0].get_header('X-lensadata-dry-run'),'true')

    def test_auth_failure_not_retried_and_secrets_required(self):
        opener=Opener(failures=1,code=401)
        with self.assertRaises(RuntimeError): sender.send_events([{'eventId':'one'}],CONFIG,opener=opener)
        self.assertEqual(len(opener.requests),1)
        with self.assertRaises(ValueError): sender.send_events([],{},opener=opener)

    def test_context_only_batch_can_update_known_downgraded_events(self):
        opener = Opener()
        sender.send_events([], CONFIG, opener=opener, history=[{'eventId': 'known-revision'}])
        self.assertEqual(len(opener.requests), 1)
        payload = json.loads(opener.requests[0].data)
        self.assertEqual(payload['events'], [])
        self.assertEqual(payload['history'][0]['eventId'], 'known-revision')

    def test_stale_server_policy_is_rejected(self):
        class OldPolicy:
            def open(self, request, timeout):
                return Response({'ok': True, 'result': {'rejected': 0}, 'policy': {'version': 'old-policy'}})
        with self.assertRaises(ValueError):
            sender.send_events([{'eventId': 'one'}], CONFIG, opener=OldPolicy())

    def test_redirects_do_not_receive_credentials(self):
        self.assertIsNone(sender.NoRedirect().redirect_request(None,None,302,'',{},'https://other.example'))


if __name__ == '__main__': unittest.main()
