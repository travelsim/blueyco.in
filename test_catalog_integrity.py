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
        # Brand-new states with no secondary sales yet may carry a null guide
        # range; they must then carry an issue price so the Estimated value
        # box falls back to the issue baseline instead of showing nothing.
        raw = get_coins_raw()
        lines = [line.strip() for line in raw.split('\n') if line.strip().startswith('{ id:')]
        self.assertGreater(len(lines), 35, 'Catalog has fewer coins than expected')
        for line in lines:
            m_id = re.search(r"id:\s*'([^']+)'", line)
            self.assertTrue(m_id, f'No id found in line: {line}')
            cid = m_id.group(1)
            self.assertIn('marketLow:', line, f'{cid} missing marketLow')
            self.assertIn('marketHigh:', line, f'{cid} missing marketHigh')
            if 'marketLow: null' in line or 'marketHigh: null' in line:
                self.assertNotIn('mintPrice: null', line, f'{cid} has no guide range and no issue price')
                self.assertRegex(line, r'mintPrice:\s*\d', f'{cid} has no guide range and no issue price')

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

    def test_till_coins_not_tagged_auspost(self):
        # Circulating till coins are struck by RAM and distributed broadly;
        # they must not carry the AUSPOST attribute pill.
        self.assertNotIn('/^s3_till_/i.test(id)', INDEX)
        fn_body = INDEX.split('function coinAttributes(coin)')[1].split('function toggleAttr')[0]
        self.assertNotIn('s3_till', fn_body)

    def test_s3_till_coins_named_consistently(self):
        # Till coins carry the character name in their title.
        raw = get_coins_raw()
        lines = [line.strip() for line in raw.split('\n') if line.strip().startswith('{ id:')]
        names = {}
        for line in lines:
            m_id = re.search(r"id:\s*'([^']+)'", line)
            m_name = re.search(r"name: '((?:[^'\\]|\\.)*)'", line)
            if m_id and m_name:
                names[m_id.group(1)] = m_name.group(1)
        self.assertEqual(names.get('s3_till_bluey'), '2026 Bluey $2 Coloured Till Coin')
        self.assertEqual(names.get('s3_till_bingo'), '2026 Bingo $2 Coloured Till Coin')


    def test_pnc_coins_carry_privy_attribute(self):
        # The ten 2024 $1 PNCs hold envelope privy-mark coins (RAM 11635-11644);
        # they must carry both PNC and PRIVY pills.
        fn_body = INDEX.split('function coinAttributes(coin)')[1].split('function toggleAttr')[0]
        self.assertIn("s1_pnc_", fn_body)

    def test_tube_sets_come_in_three_states(self):
        # Each tube set is sold sealed, opened without the chase coin, and
        # opened complete with the chase coin. All three states share the RAM
        # product code and issue price; only the sealed set carries the full
        # production figure.
        raw = get_coins_raw()
        lines = [line.strip() for line in raw.split('\n') if line.strip().startswith('{ id:')]
        by_id = {}
        for line in lines:
            m_id = re.search(r"id:\s*'([^']+)'", line)
            by_id[m_id.group(1)] = line
        for trio, code, price in (
            (('s1_10_coin_folder_set', 's1_10_coin_folder_opened', 's1_coloured_insert_variant'), '11448', '29'),
            (('s3_folder', 's3_folder_opened', 's3_folder_chase'), '11956', '34'),
        ):
            for cid in trio:
                self.assertIn(cid, by_id, f'{cid} missing from catalogue')
                self.assertRegex(by_id[cid], r'mintPrice:\s*%s(?!\d)' % price, f'{cid} wrong issue price')
            # Sealed and opened states are the same RAM product; the chase
            # state carries its own product code.
            self.assertIn("productCode: '%s'" % code, by_id[trio[0]], f'{trio[0]} wrong product code')
            self.assertIn("productCode: '%s'" % code, by_id[trio[1]], f'{trio[1]} wrong product code')
            self.assertRegex(by_id[trio[2]], r"productCode: '\d+'", f'{trio[2]} missing product code')

    def test_titles_start_with_year_and_carry_denom(self):
        # Uniform titles: every product title opens with its year, and every
        # coin title carries its $1/$2 denomination.
        raw = get_coins_raw()
        lines = [line.strip() for line in raw.split('\n') if line.strip().startswith('{ id:')]
        for line in lines:
            m_id = re.search(r"id:\s*'([^']+)'", line)
            m_name = re.search(r"name: '((?:[^'\\]|\\.)*)'", line)
            cid, name = m_id.group(1), m_name.group(1)
            self.assertRegex(name, r'^(19|20)\d\d\b', f'{cid} title missing leading year: {name}')
            m_denom = re.search(r'denomination:\s*(null|\d+)', line)
            if m_denom.group(1) != 'null':
                self.assertIn('$%s' % m_denom.group(1), name, f'{cid} title missing denomination: {name}')

    def test_titles_preserve_code_coupled_tokens(self):
        # Titles must keep code-coupled tokens. Category and frame type are
        # id-based (getCoinCategory keys off id prefixes), so every PNC id
        # uses the short PNC title form.
        raw = get_coins_raw()
        lines = [line.strip() for line in raw.split('\n') if line.strip().startswith('{ id:')]
        for line in lines:
            m_id = re.search(r"id:\s*'([^']+)'", line)
            m_name = re.search(r"name: '((?:[^'\\]|\\.)*)'", line)
            cid, name = m_id.group(1), m_name.group(1)
            if 'proof' in cid or 'silv' in cid:
                self.assertIn('Proof', name, f'{cid} title lost Proof: {name}')
            if cid.startswith('s3_pin_'):
                self.assertIn('Pin', name, f'{cid} title lost Pin: {name}')
                self.assertTrue(name.startswith('2026 Bluey Stamp and Pin Cover - '), f'{cid} wrong title format: {name}')
            if '_till_' in cid:
                self.assertIn('Till', name, f'{cid} title lost Till: {name}')
            if 'folder' in cid:
                self.assertIn('Tube & Folder Set', name, f'{cid} title lost set format: {name}')
            if 'pnc' in cid.lower():
                self.assertIn('pnc', name.lower(), f'{cid} title lost PNC: {name}')

if __name__ == '__main__':
    unittest.main()
