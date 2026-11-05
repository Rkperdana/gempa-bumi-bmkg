import re
import unittest
from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]

class DashboardMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / 'index.html').read_text(encoding='utf-8')
        cls.script = (ROOT / 'app.js').read_text(encoding='utf-8')

    def test_indonesia_land_is_pre_rendered(self):
        match = re.search(r'<g id="mapLand">([\s\S]*?)</g>', self.html)
        self.assertIsNotNone(match, 'Map requires a static SVG fallback')
        self.assertGreaterEqual(match.group(1).count('<path'), 10)

    def test_map_layers_exist(self):
        for target in ('mapSvg', 'mapGraticule', 'mapLand', 'mapLabels', 'mapPoints', 'mapTooltip'):
            self.assertIn('id="' + target + '"', self.html)

    def test_geodata_load_is_fault_tolerant(self):
        self.assertIn('if(grid)', self.script)
        self.assertIn('land.replaceChildren(fragment)', self.script)

    def test_source_in_footer_is_plain_text(self):
        footer = self.html.split('<footer class="footer">', 1)[1]
        self.assertIn('Sumber: Badan Meteorologi, Klimatologi, dan Geofisika (BMKG)', footer)
        self.assertNotIn('<a ', footer)
        self.assertNotIn('Data utama berasal dari tabel', footer)

    def test_style_files_are_loaded(self):
        for path in ('styles.css','editorial.css','map-atlas.css'):
            self.assertIn('href="' + path + '"', self.html)
            self.assertTrue((ROOT / path).exists())

if __name__ == '__main__':
    unittest.main()
