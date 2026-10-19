import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

INDEX = Path(__file__).with_name('index.html')

# Loads the real catalogue and the real coinAttributes() from index.html, so the
# tests check the COLOURED pill a visitor sees, not a copy of the rule.
RENDER_JS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.env.INDEX_PATH, 'utf8');
const start = html.indexOf('window.COINS = [');
const end = html.indexOf('\n];', start) + 3;
const COINS = new Function(html.slice(start, end).replace('window.COINS = ', 'return '))();
const attrsSrc = html.slice(html.indexOf('function coinAttributes'), html.indexOf('function toggleAttr'));
const coinAttributes = new Function(attrsSrc + '\nreturn coinAttributes;')();
const out = COINS.map(c => ({
  id: c.id,
  name: c.name,
  denomination: c.denomination,
  coloured: coinAttributes(c).includes('COLOURED'),
}));
process.stdout.write(JSON.stringify(out));
"""

# Privy-mark coins, sealed or opened folder/tube sets: the coloured coin is a
# 1-in-10 hit in a sealed tube, not part of the product, so they are not coloured.
NOT_COLOURED = [
    's1_10_coin_folder_set',
    's1_10_coin_folder_opened',
    's3_folder',
    's3_rain_privy',
    's3_sleepytime_privy',
    's3_camping_privy',
    's3_babyrace_privy',
    's3_granny_privy',
]

# Products that include a coloured coin without "coloured" in the name. Each was
# checked against the catalogue sources: the 2-coin and 3-coin PNCs include a
# coloured coin, the silver PNC has a coloured silver proof, the three-coin set
# is the coloured trio, and the 2026 PNCs carry the coloured till-coin designs.
COLOURED_WITHOUT_NAME_WORD = [
    's1_impressions_pnc_2coin',
    's1_impressions_pnc_3coin',
    's1_impressions_pnc_silver',
    's1_three_coin_set',
    's3_pnc_bluey',
    's3_pnc_bingo',
]


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class TestColouredPill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, 'INDEX_PATH': str(INDEX)}
        out = subprocess.run(['node', '-e', RENDER_JS], env=env, capture_output=True, text=True, check=True)
        cls.coins = {coin['id']: coin for coin in json.loads(out.stdout)}

    def test_privy_and_folder_sets_are_not_coloured(self):
        for coin_id in NOT_COLOURED:
            with self.subTest(coin=coin_id):
                self.assertFalse(self.coins[coin_id]['coloured'])

    def test_products_named_coloured_show_the_pill(self):
        for coin_id, coin in self.coins.items():
            name = coin['name']
            if not re.search(r'\bcoloured\b', name, re.IGNORECASE):
                continue
            with self.subTest(coin=coin_id):
                self.assertTrue(coin['coloured'], name)

    def test_reviewed_products_with_a_coloured_coin_show_the_pill(self):
        for coin_id in COLOURED_WITHOUT_NAME_WORD:
            with self.subTest(coin=coin_id):
                self.assertTrue(self.coins[coin_id]['coloured'])

    def test_non_coins_never_show_the_pill(self):
        for coin_id, coin in self.coins.items():
            if coin['denomination'] is None:
                with self.subTest(coin=coin_id):
                    self.assertFalse(coin['coloured'])


if __name__ == '__main__':
    unittest.main()
