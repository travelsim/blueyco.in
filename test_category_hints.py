import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

INDEX = Path(__file__).with_name('index.html')

# Runs the real getCoinCategory from index.html against every coin, so the
# tests check the badge and hint each card actually shows.
RENDER_JS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.env.INDEX_PATH, 'utf8');
const start = html.indexOf('window.COINS = [');
const end = html.indexOf('\n];', start) + 3;
const COINS = new Function(html.slice(start, end).replace('window.COINS = ', 'return '))();
const fnStart = html.indexOf('function getCoinCategory(coin) {');
let depth = 0, i = fnStart;
for (; i < html.length; i++) {
  if (html[i] === '{') depth++;
  else if (html[i] === '}') { depth--; if (depth === 0) break; }
}
const getCoinCategory = new Function('coin', html.slice(fnStart, i + 1).replace(/^function getCoinCategory\(coin\) \{/, '').replace(/\}$/, ''));
const out = {};
for (const coin of COINS) out[coin.id] = getCoinCategory(coin);
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class TestCategoryHints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, 'INDEX_PATH': str(INDEX)}
        out = subprocess.run(['node', '-e', RENDER_JS], env=env, capture_output=True, text=True, check=True, encoding='utf-8')
        cls.cats = json.loads(out.stdout)

    def test_proof_coins_are_not_called_uncirculated(self):
        # Proofs are struck to proof quality, not uncirculated finish.
        for coin_id, cat in self.cats.items():
            if cat.get('type') != 'colour':
                continue
            is_proof = 'proof' in coin_id or 'silv' in coin_id
            with self.subTest(coin=coin_id):
                if is_proof:
                    self.assertIn('Proof', cat['hint'], cat)
                    self.assertNotIn('Uncirculated', cat['hint'], cat)
                else:
                    self.assertIn('Uncirculated', cat['hint'], cat)

    def test_proof_hint_uses_official_finish_terms(self):
        for coin_id, cat in self.cats.items():
            if cat.get('type') == 'colour' and ('proof' in coin_id or 'silv' in coin_id):
                with self.subTest(coin=coin_id):
                    self.assertEqual(cat['hint'], 'Proof-quality strike with colour print finish.')


if __name__ == '__main__':
    unittest.main()
