import copy
import datetime as dt
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import dataloka_wp_maritim as p

NOW=dt.datetime(2026,11,28,2,tzinfo=dt.timezone.utc)
A={"kind":"wave","region":"Contoh","start":"2026-11-28T07:00:00+07:00","end":"2026-12-01T07:00:00+07:00",
   "zone":"WIB","groups":{"sedang":[],"tinggi":["Perairan Uji"],"sangat_tinggi":[],"ekstrem":[]},
   "synoptic":"Narasi sintetis.","source":p.WAVE}

class FakeWP(p.MaritimeWP):
    def __init__(self):
        self.post=None
        self.calls=[]
    def strict_tags(self,names): return [1,2,3,4]
    def berita_category_id(self): return 10
    def image_id(self,kind): return 42
    def by_slug(self,slug): return copy.deepcopy(self.post)
    def by_id(self,id): return copy.deepcopy(self.post)
    def call(self,method,route,params=None,payload=None):
        self.calls.append((method,route,payload))
        if route=="posts":
            self.post={"id":7,**copy.deepcopy(payload)}
            self.post["title"]={"raw":payload["title"]}
            self.post["content"]={"raw":payload["content"]}
        elif route=="posts/7":
            self.post.update(payload)
        else: raise AssertionError(route)
        return copy.deepcopy(self.post)

class TestPublisher(unittest.TestCase):
    def test_create_and_no_republish(self):
        wp=FakeWP(); checks=[]
        self.assertEqual(wp.publish_verified(A,checks.append,NOW),7)
        self.assertEqual(len(checks),2)
        self.assertEqual(wp.post["status"],"publish")
        self.assertEqual(wp.post["featured_media"],42)
        self.assertEqual(wp.publish_verified(A,checks.append,NOW+dt.timedelta(days=1)),7)
        self.assertEqual(len(wp.calls),2)
    def test_revalidate_before_publish(self):
        wp=FakeWP()
        def check(a):
            if wp.post: raise RuntimeError("expired")
        with self.assertRaises(RuntimeError): wp.publish_verified(A,check,NOW)
        self.assertEqual(wp.post["status"],"draft")
    def test_edited_draft_protected(self):
        wp=FakeWP()
        with self.assertRaises(RuntimeError):
            wp.publish_verified(A,lambda a: (_ for _ in ()).throw(RuntimeError("expired")) if wp.post else None,NOW)
        wp.post["content"]["raw"]="Edited by editor"
        with self.assertRaises(p.EditorialConflict): wp.publish_verified(A,lambda a:None,NOW)
        self.assertEqual(wp.post["status"],"draft")
    def test_source_denial_never_contacts_wordpress(self):
        with patch.dict(os.environ,{"BMKG_MARITIM_AUTHORIZED":"true","BMKG_MARITIM_LIVE":"true"}), \
            patch.object(p,"fetch",side_effect=RuntimeError("403")),patch.object(p,"MaritimeWP") as wp:
            with self.assertRaises(RuntimeError): p.live_wave(NOW)
            wp.assert_not_called()
    def test_live_gate(self):
        with patch.dict(os.environ,{"BMKG_MARITIM_AUTHORIZED":"true","BMKG_MARITIM_LIVE":"false"}):
            with self.assertRaises(PermissionError): p.live_wave(NOW)

    def test_reviewed_approval_required(self):
        with patch.dict(os.environ,{"BMKG_MARITIM_REVIEWED_APPROVED":"false"}):
            with self.assertRaises(PermissionError): p.reviewed_wave("missing.json")
    def test_stale_review_cannot_contact_wordpress(self):
        from tempfile import TemporaryDirectory
        import json
        with TemporaryDirectory() as temp:
            path=Path(temp)/"snapshot.json"
            path.write_text(json.dumps({"source":p.WAVE,"checked_at":"2020-01-01T00:00:00Z","bulletin":{"Indonesia":{}}}))
            with patch.dict(os.environ,{"BMKG_MARITIM_REVIEWED_APPROVED":"true"}),patch.object(p,"MaritimeWP") as wp:
                with self.assertRaisesRegex(RuntimeError,"older than"): p.reviewed_wave(path)
                wp.assert_not_called()

if __name__=="__main__": unittest.main()
