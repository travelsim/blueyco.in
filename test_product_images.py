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
    # The folder-set products used derived composite packshots until 29 Nov 2026,
    # when James asked for official images only. They now show the official
    # folder photo, and no product may use a derived composite again.
    def test_folder_set_products_show_official_images_not_composites(self):
        block = INDEX.split('const COIN_PRODUCT_IMAGES = {')[1].split('};')[0]
        self.assertNotIn('Derived composite', block)
        for coin_id in ('s1_10_coin_folder_opened', 's1_coloured_insert_variant', 's3_folder_opened', 's3_folder_chase'):
            entry = re.search(rf"{coin_id}:\s*\{{[^}}]*\}}", block).group(0)
            self.assertNotRegex(entry, r"2024-coloured-insert-variant|2024-folder-set-opened|2026-folder-set-opened|2026-folder-set-chase")
            self.assertRegex(entry, r"source: 'https://")

