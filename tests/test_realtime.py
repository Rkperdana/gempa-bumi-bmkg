import unittest
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('update_data',Path(__file__).parents[1]/'scripts'/'update_data.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

CELLS=['1','5 Nov 2026 09.52.30 WIB','3,8','10 Km','5,97 LS-130,26 BT','Banda Sea','–','Lihat']

class RealtimeTests(unittest.TestCase):
    def test_parse_realtime_row(self):
        e=m.parse_realtime_row(CELLS)
        self.assertEqual(e['datetime'],'2026-11-05T02:52:30Z')
        self.assertEqual(e['lat'],-5.97)
        self.assertEqual(e['lon'],130.26)
        self.assertEqual(e['magnitude'],3.8)
        self.assertIn('realtime',e['source_types'])

    def test_west_longitude(self):
        e=m.parse_realtime_row(CELLS[:4]+['19,16 LS-177,57 BB']+CELLS[5:])
        self.assertEqual(e['lon'],-177.57)

    def test_invalid_coords_fail(self):
        with self.assertRaises(ValueError):
            m.parse_realtime_row(CELLS[:4]+['bad coordinates']+CELLS[5:])

    def test_parser_rejects_partial_page(self):
        html='<html><table><tr>'+''.join('<td>'+c+'</td>' for c in CELLS)+'</tr></table></html>'
        with self.assertRaises(ValueError):
            m.parse_realtime_html(html)

    def test_many_rows_succeed(self):
        from datetime import datetime, timedelta
        start=datetime(2026,11,5,9,52,30)
        html=['<table><tbody>']
        for i in range(115):
            moment=start-timedelta(minutes=i)
            cells=[str(i+1),moment.strftime('%d Nov %Y %H.%M.%S WIB'),'3,8','10 Km',f'{5+i/100:.2f} LS-130,26 BT','Banda Sea','–','Lihat']
            html.append('<tr>'+''.join('<td>'+c+'</td>' for c in cells)+'</tr>')
        html.append('</tbody></table>')
        events=m.parse_realtime_html(''.join(html))
        self.assertEqual(len(events),115)
        self.assertGreater(events[0]['datetime'],events[-1]['datetime'])

    def test_enrichment_does_not_override_realtime_magnitude(self):
        e=m.parse_realtime_row(CELLS)
        supplemental={'DateTime':e['datetime'],'Coordinates':f"{e['lat']},{e['lon']}",'Magnitude':'4.1','Kedalaman':'12 km','Wilayah':'Banda Sea', 'Dirasakan':'II Ambon'}
        feed={'felt':{'Infogempa':{'gempa':[supplemental]}}}
        events,errors=m.enrich_realtime([e],feed,[],'2026-11-05T03:00:00Z')
        self.assertEqual(errors,[])
        self.assertEqual(events[0]['magnitude'],3.8)
        self.assertEqual(events[0]['depth_km'],10)
        self.assertTrue(events[0]['felt'])

if __name__=='__main__':
    unittest.main()
