import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('updater',Path(__file__).parents[1]/'scripts/update_data.py')
updater=importlib.util.module_from_spec(spec);spec.loader.exec_module(updater)
BASE={'id':'old-derived','datetime':'2026-11-13T00:00:00Z','magnitude':5.5,'depth_km':20,'lat':-8.0,'lon':120.0,'region':'Flores Region, Indonesia','first_seen_at':'first'}
class Revisions(unittest.TestCase):
 def test_coordinate_revision_retains_id_and_first_seen(self):
  current={**BASE,'id':'new-derived','lat':-8.1,'magnitude':5.3,'depth_km':22}
  rows,_=updater.enrich_realtime([current],{},[BASE],'now')
  self.assertEqual(rows[0]['id'],'old-derived');self.assertEqual(rows[0]['first_seen_at'],'first');self.assertEqual(rows[0]['magnitude'],5.3)
 def test_coexisting_source_rows_are_not_merged(self):
  close={**BASE,'id':'another','lat':-8.01}
  rows,_=updater.enrich_realtime([dict(BASE),close],{},[BASE],'now')
  self.assertEqual([x['id'] for x in rows],['old-derived','another'])
 def test_ambiguous_previous_candidates_are_not_merged(self):
  current={**BASE,'id':'new-derived','lat':-8.02}
  rows,_=updater.enrich_realtime([current],{},[BASE,{**BASE,'id':'other-old','lat':-8.01}],'now')
  self.assertEqual(rows[0]['id'],'new-derived')
 def test_distant_events_are_not_merged(self):
  current={**BASE,'id':'new-derived','lat':0}
  rows,_=updater.enrich_realtime([current],{},[BASE],'now')
  self.assertEqual(rows[0]['id'],'new-derived')
if __name__=='__main__':unittest.main()
