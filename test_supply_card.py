import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

INDEX = Path(__file__).with_name('index.html')

# Runs the real Mintage/Produced block from index.html against every coin and
# prints the text each card shows, so the tests check what a visitor reads.
RENDER_JS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.env.INDEX_PATH, 'utf8');
const start = html.indexOf('window.COINS = [');
const end = html.indexOf('\n];', start) + 3;
const COINS = new Function(html.slice(start, end).replace('window.COINS = ', 'return '))();
const lines = html.split('\n');
const first = lines.findIndex(l => l.includes("const supplyCard = el('section'"));
const last = lines.findIndex(l => l.includes('if (supplyDetail) supplyCard.append'));
const runCard = new Function('el', 'coin', lines.slice(first, last + 1).join('\n') + '\nreturn supplyCard;');
function el(tag, cls, text) {
  const node = { text: text === undefined ? null : String(text), children: [] };
  node.append = (...kids) => node.children.push(...kids);
  node.setAttribute = () => {};
  return node;
}
function texts(node, out) {
  if (node.text) out.push(node.text);
  node.children.forEach(child => texts(child, out));
  return out;
}
const cards = {};
for (const coin of COINS) cards[coin.id] = texts(runCard(el, coin), []);
process.stdout.write(JSON.stringify(cards));
"""


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class TestSupplyCardText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, 'INDEX_PATH': str(INDEX)}
        out = subprocess.run(['node', '-e', RENDER_JS], env=env, capture_output=True, text=True, check=True)
        cls.cards = json.loads(out.stdout)

    def test_pnc_family_states_each_fact_once(self):
        # The Produced card carries the 6,500 figure and its unit, so the
        # Mintage side must not repeat the word "mintage" or the figure.
        self.assertEqual(self.cards['s1_pnc_family'], ['Mintage', 'Unlimited', 'Produced', '6,500', 'covers'])

    def test_word_produced_appears_once_per_card(self):
        for coin_id, card in self.cards.items():
            with self.subTest(coin=coin_id):
                self.assertLessEqual(sum('produced' in text.lower() for text in card), 1, card)

    def test_unpublished_mintage_has_no_caption_repeating_its_label(self):
        self.assertEqual(self.cards['s3_maxicard_pack'], ['Mintage', 'Unpublished', 'Produced', 'Not published'])

    def test_covers_mintage_is_not_labelled_as_coins(self):
        self.assertEqual(self.cards['s1_impressions_pnc_2coin'], ['Mintage', '1,300', 'Produced', '1,300', 'covers'])

    def test_production_unit_follows_the_product(self):
        self.assertEqual(self.cards['s1_pnc_set_ten'][-1], 'sets')
        self.assertEqual(self.cards['s1_10_coin_folder_set'][-1], 'units')

    def test_mintage_caption_kept_when_it_adds_information(self):
        self.assertIn('mintage ceiling (5,000 carded / 25,000 in sets)', self.cards['s1_coloured_bluey'])
        self.assertIn('covers issued (5,000 coins struck by RAM)', self.cards['s1_impressions_pnc_colour'])


if __name__ == '__main__':
    unittest.main()
