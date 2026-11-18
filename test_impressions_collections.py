import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

INDEX = Path(__file__).with_name('index.html')
HTML = INDEX.read_text(encoding='utf-8')

# Loads the real catalogue and the real coinAttributes() from index.html,
# so the tests check the pills a visitor sees, not a copy of the rule.
RENDER_JS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.env.INDEX_PATH, 'utf8');
const start = html.indexOf('window.COINS = [');
const end = html.indexOf('\n];', start) + 3;
const COINS = new Function(html.slice(start, end).replace('window.COINS = ', 'return '))();
const attrsSrc = html.slice(html.indexOf('function coinAttributes'), html.indexOf('function toggleAttr'));
const coinAttributes = new Function(attrsSrc + '\nreturn coinAttributes;')();
process.stdout.write(JSON.stringify(COINS.map(c => ({ id: c.id, name: c.name, series: c.series, mintage: c.mintage, issueQuantity: c.issueQuantity, mintPrice: c.mintPrice, attrs: coinAttributes(c) }))));
"""

MINISHEETS = [
    's1_impressions_2coin_privy_minisheet_bluey',
    's1_impressions_2coin_privy_minisheet_heelers',
    's1_impressions_2coin_privy_minisheet_blueybingofriends',
    's1_impressions_2coin_privy_minisheet_stripes',
    's1_impressions_2coin_privy_minisheet_bingo',
    's1_impressions_2coin_privy_minisheet_mumdad',
    's1_impressions_2coin_privy_minisheet_grannies',
    's1_impressions_2coin_privy_minisheet_radfrisky',
    's1_impressions_2coin_privy_minisheet_blueyfriends',
    's1_impressions_2coin_privy_minisheet_muffinsocks',
]

COVER_QTY = {
    's1_impressions_pnc_colour': 3000,
    's1_impressions_pnc_2coin': 1300,
    's1_impressions_pnc_3coin': 700,
    's1_impressions_pnc_silver': 150,
    's1_impressions_2coin_privy_minisheet_set': 100,
}


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class TestImpressionsCollections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, 'INDEX_PATH': str(INDEX)}
        out = subprocess.run(['node', '-e', RENDER_JS], env=env, capture_output=True, text=True, check=True, encoding='utf-8')
        cls.coins = {coin['id']: coin for coin in json.loads(out.stdout)}

    def test_section_has_fifteen_products(self):
        november = [c for c in self.coins.values() if c['series'] == 'series1_november']
        self.assertEqual(len(november), 15)
        for coin_id in ['s1_impressions_pnc_colour', 's1_impressions_pnc_2coin', 's1_impressions_pnc_3coin', 's1_impressions_pnc_silver'] + MINISHEETS + ['s1_impressions_2coin_privy_minisheet_set']:
            self.assertIn(coin_id, self.coins)

    def test_section_label_is_2024_bluey_impressions(self):
        self.assertIn('>2024 Bluey Impressions</button>', HTML)
        self.assertIn("series1_november: '2024 Bluey Impressions'", HTML)
        self.assertNotIn('November 2024 - Impressions PNCs', HTML)
        self.assertNotIn('November 2024 PNCs</option>', HTML)

    def test_pncs_show_only_cover_production(self):
        # Coin mintages live on the original coin products; these cards show
        # only their cover production quantity (mintage null).
        for coin_id, qty in COVER_QTY.items():
            with self.subTest(coin_id=coin_id):
                self.assertIsNone(self.coins[coin_id]['mintage'])
                self.assertEqual(self.coins[coin_id]['issueQuantity'], qty)
        for coin_id in MINISHEETS:
            with self.subTest(coin_id=coin_id):
                self.assertIsNone(self.coins[coin_id]['mintage'])
                self.assertEqual(self.coins[coin_id]['issueQuantity'], 200)
                self.assertEqual(self.coins[coin_id]['mintPrice'], 70)

    def test_pnc_titles_carry_metal_and_finish(self):
        self.assertIn('AlBr Coloured Coin PNC', self.coins['s1_impressions_pnc_colour']['name'])
        self.assertIn('AlBr 2-Coin PNC', self.coins['s1_impressions_pnc_2coin']['name'])
        self.assertIn('AlBr 3-Coin PNC', self.coins['s1_impressions_pnc_3coin']['name'])
        silver = self.coins['s1_impressions_pnc_silver']['name']
        self.assertIn('Silver', silver)
        self.assertIn('Coloured', silver)
        self.assertIn('Proof', silver)

    def test_pnc_attributes(self):
        for coin_id in ('s1_impressions_pnc_colour', 's1_impressions_pnc_2coin', 's1_impressions_pnc_3coin', 's1_impressions_pnc_silver'):
            with self.subTest(coin_id=coin_id):
                attrs = self.coins[coin_id]['attrs']
                self.assertIn('PNC', attrs)
                self.assertIn('COLOURED', attrs)
                self.assertIn('AUSPOST', attrs)
                self.assertIn('RAM', attrs)
        self.assertIn('UNC', self.coins['s1_impressions_pnc_colour']['attrs'])
        self.assertNotIn('PROOF', self.coins['s1_impressions_pnc_colour']['attrs'])
        self.assertIn('SET', self.coins['s1_impressions_pnc_2coin']['attrs'])
        self.assertIn('SET', self.coins['s1_impressions_pnc_3coin']['attrs'])
        self.assertIn('PRIVY', self.coins['s1_impressions_pnc_3coin']['attrs'])
        self.assertNotIn('PRIVY', self.coins['s1_impressions_pnc_2coin']['attrs'])
        self.assertIn('PROOF', self.coins['s1_impressions_pnc_silver']['attrs'])
        self.assertNotIn('UNC', self.coins['s1_impressions_pnc_silver']['attrs'])

    def test_minisheet_attributes_and_no_colour_or_proof(self):
        for coin_id in MINISHEETS:
            with self.subTest(coin_id=coin_id):
                attrs = self.coins[coin_id]['attrs']
                for attr in ('UNC', 'STAMP', 'SET', 'PRIVY', 'AUSPOST', 'RAM'):
                    self.assertIn(attr, attrs)
                self.assertNotIn('COLOURED', attrs)
                self.assertNotIn('PROOF', attrs)
                self.assertNotIn('PNC', attrs)
                self.assertIn('Minisheet Collection - ', self.coins[coin_id]['name'])
        set_attrs = self.coins['s1_impressions_2coin_privy_minisheet_set']['attrs']
        for attr in ('UNC', 'STAMP', 'SET', 'PRIVY', 'AUSPOST', 'RAM'):
            self.assertIn(attr, set_attrs)


if __name__ == '__main__':
    unittest.main()
