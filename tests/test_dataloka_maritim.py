import datetime as dt
import io
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import dataloka_maritim as m

NOW=dt.datetime(2026,11,28,2,tzinfo=dt.timezone.utc)
def wave():
    return {"Contoh Wilayah":{"data":{"region":"Contoh Wilayah","synoptic":"Angin bertiup dari timur.",
        "valid_from":"2026-11-28T07:00","valid_until":"2026-12-01T07:00","time_zone":"WIB",
        "warning":{"sedang":["Perairan B"],"tinggi":["Perairan A"],"sangat_tinggi":[],"ekstrem":[]}}}}
class MaritimeTests(unittest.TestCase):
    def test_wave(self):
        a=m.parse_wave(wave(),NOW)[0]
        p=m.article(a,NOW)
        self.assertTrue(p["title"].startswith("BMKG:"))
        self.assertIn("2,5–4 meter",p["content"])
        self.assertIn("Perairan B",p["content"])
        self.assertIn("07.00 WIB",p["content"])
        self.assertEqual(p["status"],"preview")
        self.assertNotIn("Featured",p["tag_names"])
        self.assertEqual(p["slug"],m.article(a,NOW)["slug"])
    def test_expired_and_medium_only(self):
        self.assertEqual(m.parse_wave(wave(),NOW+dt.timedelta(days=5)),[])
        raw=wave()
        raw["Contoh Wilayah"]["data"]["warning"]["tinggi"]=[]
        self.assertEqual(m.parse_wave(raw,NOW),[])
    def test_fail_closed_schema(self):
        raw=wave()
        del raw["Contoh Wilayah"]["data"]["warning"]["ekstrem"]
        with self.assertRaises(ValueError): m.parse_wave(raw,NOW)
    def test_rob(self):
        raw=[{"region":"Contoh Pesisir","start":"2026-11-28","end":"2026-11-30","zone":"WIB",
            "areas":["<script>"],"description":"Ilustrasi data uji."}]
        a=m.parse_reviewed_rob(raw,NOW)[0]
        p=m.article(a,NOW)
        self.assertTrue(p["title"].startswith("BMKG: Waspada Banjir Rob"))
        self.assertNotIn("<script>",p["content"])
        self.assertEqual(m.parse_reviewed_rob(raw,NOW+dt.timedelta(days=5)),[])
    def test_permission_gate(self):
        with patch.dict(os.environ,{"BMKG_MARITIM_AUTHORIZED":"false"}):
            with self.assertRaises(PermissionError): m.fetch(m.WAVE)
    def test_covers(self):
        for kind in ("rob","wave"):
            data=m.cover(kind)
            self.assertLess(len(data),600000)
            im=Image.open(io.BytesIO(data))
            self.assertEqual(im.size,(1600,900))
            self.assertEqual(im.format,"JPEG")

if __name__=="__main__": unittest.main()
