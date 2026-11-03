import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
INDEX = (ROOT / 'index.html').read_text(encoding='utf-8')


def get_coins_raw():
    match = re.search(r'window\.COINS\s*=\s*\[([\s\S]*?)\n\];', INDEX)
    assert match, 'window.COINS not found in index.html'
    return match.group(1)


class TestCatalogIntegrity(unittest.TestCase):
    def test_all_coins_have_market_ranges(self):
        # Ensure no coins have null or missing marketLow/marketHigh
        raw = get_coins_raw()
        lines = [line.strip() for line in raw.split('\n') if line.strip().startswith('{ id:')]
        self.assertGreater(len(lines), 35, 'Catalog has fewer coins than expected')
        for line in lines:
            m_id = re.search(r"id:\s*'([^']+)'", line)
            self.assertTrue(m_id, f'No id found in line: {line}')
            cid = m_id.group(1)
            self.assertIn('marketLow:', line, f'{cid} missing marketLow')
            self.assertIn('marketHigh:', line, f'{cid} missing marketHigh')
            self.assertNotIn('marketLow: null', line, f'{cid} has marketLow: null')
            self.assertNotIn('marketHigh: null', line, f'{cid} has marketHigh: null')

    def test_ram_2023_24_annual_report_figures(self):
        raw = get_coins_raw()
        # s1_three_coin_set: produced 25,000, mintage ceiling 30,000
        self.assertRegex(raw, r"id:\s*'s1_three_coin_set'[\s\S]*?mintage:\s*30000[\s\S]*?issueQuantity:\s*25000")
        # s1_coloured_bluey / heelers / grannies: produced 5,000 carded, mintage 30,000 ceiling
        for cid in ('s1_coloured_bluey', 's1_coloured_heelers', 's1_coloured_grannies'):
            pattern = r"id:\s*'" + cid + r"'[\s\S]*?mintage:\s*30000[\s\S]*?issueQuantity:\s*5000"
            self.assertRegex(raw, pattern)
        # Folder & lucky hit: 11448 produced 157,500; 31961 produced 15,750
        self.assertRegex(raw, r"id:\s*'s1_10_coin_folder_set'[\s\S]*?issueQuantity:\s*157500")
        self.assertRegex(raw, r"id:\s*'s1_coloured_insert_variant'[\s\S]*?productCode:\s*'31961'[\s\S]*?issueQuantity:\s*15750")
        # Till coins: 1,250,000 produced
        self.assertRegex(raw, r"id:\s*'s1_bluey'[\s\S]*?issueQuantity:\s*1250000")
        self.assertRegex(raw, r"id:\s*'s1_bingo'[\s\S]*?issueQuantity:\s*1250000")
        # Cards: 7,250 produced (7,252 for 11435)
        self.assertRegex(raw, r"id:\s*'s1_card_bluey'[\s\S]*?issueQuantity:\s*7250")
        self.assertRegex(raw, r"id:\s*'s1_card_blueybingofriends'[\s\S]*?issueQuantity:\s*7252")
        # Proofs & PNCs from Page 5:
        # 11624: Coloured proof (5,000 produced, 5,000 mintage)
        self.assertRegex(raw, r"id:\s*'s1_proof_coloured'[\s\S]*?productCode:\s*'11624'[\s\S]*?issueQuantity:\s*5000")
        # 11645: Silver proof PNC (150 produced, 2,650 mintage)
        self.assertRegex(raw, r"id:\s*'s1_impressions_pnc_silver'[\s\S]*?productCode:\s*'11645'[\s\S]*?issueQuantity:\s*150")
        # 11450: Coloured uncirculated coin PNC (5,000 produced)
        self.assertRegex(raw, r"id:\s*'s1_impressions_pnc_colour'[\s\S]*?productCode:\s*'11450'[\s\S]*?issueQuantity:\s*5000")

    def test_folder_set_states_share_issue_price(self):
        # All three 10-coin folder set states derive from RAM product 11448,
        # issued at $29: sealed, opened base set, and lucky coloured insert.
        raw = get_coins_raw()
        lines = [line.strip() for line in raw.split('\n') if line.strip().startswith('{ id:')]
        by_id = {}
        for line in lines:
            m_id = re.search(r"id:\s*'([^']+)'", line)
            self.assertTrue(m_id, f'No id found in line: {line[:80]}')
            by_id[m_id.group(1)] = line
        for cid in ('s1_10_coin_folder_set', 's1_10_coin_folder_opened', 's1_coloured_insert_variant'):
            self.assertIn(cid, by_id, f'{cid} missing from catalogue')
            self.assertRegex(by_id[cid], r'mintPrice:\s*29(?![\d.])', f'{cid} missing $29 issue price')

    def test_estimated_value_kicker_is_universal(self):
        # Verify buildCard unconditionally sets priceHeading to 'Estimated value'
        self.assertIn("const priceHeading = 'Estimated value';", INDEX)
        self.assertIn("function _guidePrice(coin)", INDEX)
        self.assertIn("return _guidePrice(coin);", INDEX)

    def test_collector_guide_strip_present(self):
        self.assertIn('collector-guide-strip', INDEX)
        self.assertIn('Pocket Change Hunt', INDEX)
        self.assertIn('Lucky 1-in-10 Coins', INDEX)
        self.assertIn('3 Folder States', INDEX)

    def test_community_and_events_section_present(self):
        self.assertIn('href="#events"', INDEX)
        self.assertIn('id="events"', INDEX)
        self.assertIn('Melbourne Money Expo', INDEX)
        self.assertIn('Sydney Money Expo', INDEX)
        self.assertIn('Brisbane Money Expo', INDEX)
        self.assertIn('Petersham Coin & Stamp Fair', INDEX)
        self.assertIn('Moonee Ponds Coin Fair', INDEX)
        self.assertIn('r/AustralianCoins', INDEX)


class TestAttributePills(unittest.TestCase):
    def test_canonical_attributes_literal(self):
        match = re.search(r"const ATTRIBUTES = (\[[^\]]*\]);", INDEX)
        self.assertTrue(match, 'ATTRIBUTES literal not found')
        attrs = re.findall(r"'([^']+)'", match.group(1))
        self.assertEqual(attrs, ['UNC', 'PROOF', 'COLOURED', 'PNC', 'STAMP', 'SET', 'PRIVY', 'PIN', 'TILL COIN', 'AUSPOST', 'RAM'])

    def test_attribute_filter_pipeline_present(self):
        self.assertIn('function coinAttributes(coin)', INDEX)
        self.assertIn('id="attr-filters"', INDEX)
        self.assertIn('function buildAttrFilters()', INDEX)
        self.assertIn('function toggleAttr(attr)', INDEX)
        self.assertIn('activeAttrs.size > 0', INDEX)
        self.assertIn('[...activeAttrs].every(a => coinAttributes(c).includes(a))', INDEX)
        self.assertIn("/\\bset\\b/i.test(coin.name || '')", INDEX)
        self.assertIn('buildAttrFilters();', INDEX)

    def test_cards_show_attr_pills_not_legacy_tags(self):
        self.assertIn('card-attr-pills', INDEX)
        self.assertNotIn("el('span', 'card-format'", INDEX)
        self.assertNotIn('catBadge', INDEX)


if __name__ == '__main__':
    unittest.main()
