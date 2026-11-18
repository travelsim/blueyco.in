import unittest
import server

class PncListingMatchingTests(unittest.TestCase):
    def matches(self, coin_id, title):
        return server._coinxchange_title_matches(title, server._browse_keywords(server.COIN_BY_ID[coin_id]['search']))

    def test_seller_pnc_wording_matches_corresponding_cover(self):
        examples = [
            ('s1_pnc_bingo', '2024 Bluey $1 Privy Mark Postal Numismatic Cover / PNC Bingo'),
            ('s1_pnc_mumdad', '2024 Australia Bluey $1 Coin Privy Mark PNC Stamp & Coin Cover Mum & Dad'),
            ('s1_pnc_radfrisky', 'Bluey Uncle Rad & Frisky 2024 PNC the $1 coin has an envelope privy mark'),
        ]
        for coin, title in examples:
            with self.subTest(coin=coin): self.assertTrue(self.matches(coin, title))

    def test_other_character_and_sets_do_not_match(self):
        self.assertFalse(self.matches('s1_pnc_bingo', '2024 Bluey Mum & Dad PNC'))
        self.assertFalse(self.matches('s1_pnc_bingo', '2024 Australia Bluey $1 Coin Privy Mark PNC Stamp & Coin Cover Bluey,Bingo Fr'))
        self.assertFalse(self.matches('s1_pnc_bingo', '2024 Bluey Bingo PNC and card set'))
        self.assertFalse(self.matches('s1_pnc_mumdad', '2024 Bluey Bingo PNC'))
