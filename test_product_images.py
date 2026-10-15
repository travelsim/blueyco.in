import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
INDEX = (ROOT / 'index.html').read_text(encoding='utf-8')
IMAGES_DIR = ROOT / 'coin-images'


def product_map():
    block = INDEX.split('const COIN_PRODUCT_IMAGES = {')[1].split('};')[0]
    return dict(re.findall(r"^\s*([A-Za-z0-9_]+):\s*\{\s*src:\s*'([^']+)'", block, re.M))


class TestProductImagesExist(unittest.TestCase):
    def test_every_mapped_product_image_is_on_disk(self):
        images = product_map()
        self.assertTrue(images, 'no COIN_PRODUCT_IMAGES mapping found')
        for coin_id, src in images.items():
            self.assertTrue((ROOT / src).exists(), f'{coin_id} -> {src} missing')


class TestDerivedImagesAreHonest(unittest.TestCase):
    # The folder-set fixes are derived packshots: their credit must never
    # claim to be official photography (Oct 2026: the coloured-variant alt
    # text claimed an official RAM image over an empty folder render).
    def test_folder_set_fixes_show_derived_credit(self):
        block = INDEX.split('const COIN_PRODUCT_IMAGES = {')[1].split('};')[0]
        for coin_id in ('s1_10_coin_folder_opened', 's1_coloured_insert_variant'):
            entry = re.search(rf"{coin_id}:\s*\{{[^}}]*\}}", block).group(0)
            self.assertIn('Derived', entry)
            self.assertNotIn('Official', entry)

