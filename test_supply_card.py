import json
import os
import re
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
const last = lines.findIndex(l => l.includes('if (supplyDetail) more.append'));
// The real card passes its More details block as \`more\`; the captured text includes it.
const runCard = new Function('el', 'coin', "const more = el('details', 'card-more');\n" + lines.slice(first, last + 1).join('\n') + '\nreturn [supplyCard, more];');
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
for (const coin of COINS) {
  const [supply, more] = runCard(el, coin);
  cards[coin.id] = texts(more, texts(supply, []));
}
process.stdout.write(JSON.stringify(cards));
"""


def coin_ram_flags():
    """Map coin id -> (has numeric mintage, has denomination).

    Only a numeric mintage on a coin product (denomination set) counts as a
    RAM-published mintage. Catalogue field order is stable: denomination and
    mintage both appear within the first entries of each record.
    """
    body = re.search(r'window\.COINS = \[(.*?)\];', INDEX.read_text(encoding='utf-8'), re.S).group(1)
    flags = {}
    for m in re.finditer(r"\{\s*id: '([^']+)'", body):
        window = body[m.start():m.start() + 1200]
        mint = re.search(r'mintage: (null|\d+)', window)
        denom = re.search(r'denomination: (null|\d+)', window)
        assert mint and denom, m.group(1)
        flags[m.group(1)] = (mint.group(1) != 'null', denom.group(1) != 'null')
    return flags


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class TestSupplyCardText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, 'INDEX_PATH': str(INDEX)}
        out = subprocess.run(['node', '-e', RENDER_JS], env=env, capture_output=True, text=True, check=True)
        cls.cards = json.loads(out.stdout)

    def test_pnc_family_states_each_fact_once(self):
        # The 6,500 production figure stands in as the mintage in a single
        # block, so the separate Produced block is skipped, not repeated.
        self.assertEqual(self.cards['s1_pnc_family'], ['Mintage', '6,500', 'covers'])

    def test_word_produced_appears_once_per_card(self):
        for coin_id, card in self.cards.items():
            with self.subTest(coin=coin_id):
                self.assertLessEqual(sum('produced' in text.lower() for text in card), 1, card)

    def test_unpublished_mintage_has_no_caption_repeating_its_label(self):
        self.assertEqual(self.cards['s3_maxicard_pack'], ['Produced', 'Not published'])

    def test_covers_mintage_is_not_labelled_as_coins(self):
        self.assertEqual(self.cards['s1_impressions_pnc_2coin'], ['Mintage', '1,300', 'Produced', '1,300', 'covers'])

    def test_production_unit_follows_the_product(self):
        self.assertEqual(self.cards['s1_pnc_set_ten'][-1], 'sets')
        self.assertEqual(self.cards['s1_10_coin_folder_set'][-1], 'units')

    def test_mintage_caption_kept_when_it_adds_information(self):
        self.assertIn('mintage ceiling (5,000 carded / 25,000 in sets)', self.cards['s1_coloured_bluey'])
        self.assertIn('covers issued (5,000 coins struck by RAM)', self.cards['s1_impressions_pnc_colour'])

    def test_production_figure_stands_in_as_single_mintage_block(self):
        # Products without a RAM mintage show the production figure under
        # Mintage with its unit, and no separate Produced block.
        self.assertEqual(self.cards['s1_card_bluey'], ['Mintage', '7,250', 'units'])
        self.assertEqual(self.cards['s1_bluey'], ['Mintage', '1,250,000', 'units'])
        self.assertEqual(self.cards['s3_folder'], ['Mintage', '15,000', 'units'])

    def test_pin_covers_have_no_mintage_and_no_published_coins(self):
        for coin_id in ('s3_pin_babyrace', 's3_pin_camping', 's3_pin_granny', 's3_pin_rain', 's3_pin_sleepytime'):
            with self.subTest(coin=coin_id):
                self.assertEqual(self.cards[coin_id], ['Produced', 'Not published'])

    def test_products_without_any_figure_have_no_mintage(self):
        for coin_id in ('s0_2020_stamp_pack', 's1_auspost_stamp_pack', 's2_xmas_stamp_pack',
                        's3_stamp_pack', 's3_maxicard_pack', 's3_till_bluey', 's3_till_bingo',
                        's3_sleepytime_insert'):
            with self.subTest(coin=coin_id):
                self.assertNotIn('Mintage', self.cards[coin_id])

    def test_no_guide_range_footnote_text(self):
        # The "Guide range $X – $Y · Collector estimate" footnote was removed
        # from the Estimated value box; it must not appear anywhere.
        self.assertNotIn('Guide range', INDEX.read_text(encoding='utf-8'))

    def test_published_coins_only_on_ram_coin_mintages(self):
        flags = coin_ram_flags()
        self.assertEqual(set(flags), set(self.cards))
        for coin_id, card in self.cards.items():
            has_ram_mintage, has_denom = flags[coin_id]
            with self.subTest(coin=coin_id):
                if has_ram_mintage and has_denom:
                    continue  # RAM coin mintages keep the wording where it adds information.
                self.assertNotIn('published coins', card)


if __name__ == '__main__':
    unittest.main()
