import unittest
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('update_data',Path(__file__).parents[1] / 'scripts' / 'update_data.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SAMPLE = {'DateTime':'2026-11-04T07:56:34+00:00','Coordinates':'-1.14,120.15','Magnitude':'3.4','Kedalaman':'10 km','Wilayah':'40 km timur laut Sigi', 'Dirasakan':'III Sigi'}

class IngestTests(unittest.TestCase):
    def test_felt_below_five_included(self):
        e=m.parse_event(SAMPLE,'felt')
        self.assertTrue(e['felt'])
        self.assertEqual(e['magnitude'],3.4)
    def test_latest_unfelt_small_excluded(self):
        s={**SAMPLE,'Dirasakan':''}
        self.assertIsNone(m.parse_event(s,'latest'))
    def test_crossfeed_merges(self):
        s={**SAMPLE,'Magnitude':'5.4'}
        feeds={'latest':{'Infogempa':{'gempa':s}},'felt':{'Infogempa':{'gempa':s}},'m5':{'Infogempa':{'gempa':s}}}
        events,issues=m.ingest([],feeds,'2026-11-05T00:00:00Z')
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['source_types'],['felt','latest','m5'])
    def test_invalid_coordinates(self):
        with self.assertRaises(ValueError):
            m.parse_event({**SAMPLE,'Coordinates':'bogus'},'felt')
    def test_unsafe_tsunami_negation(self):
        e=m.parse_event({**SAMPLE,'Potensi':'Tidak berpotensi tsunami'},'felt')
        self.assertFalse(e['tsunami'])
    def test_tsunami_revocation_replaces_alert(self):
        yes=m.parse_event({**SAMPLE, 'Magnitude':'6.1', 'Potensi':'Berpotensi tsunami'},'latest')
        no=m.parse_event({**SAMPLE, 'Magnitude':'6.1', 'Potensi':'Tidak berpotensi tsunami'},'latest')
        self.assertTrue(yes['tsunami'])
        self.assertFalse(m.merge(yes,no)['tsunami'])
    def test_partial_failure_no_silent_success(self):
        with self.assertRaises(ValueError):
            m.ingest([],{'felt':{'Infogempa':{'gempa':[]}}},'2026-11-05T00:00:00Z')

if __name__=='__main__':unittest.main()
