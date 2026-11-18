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
        for coin_id in ('s1_10_coin_folder_opened', 's1_coloured_insert_variant', 's3_folder_opened', 's3_folder_chase'):
            entry = re.search(rf"{coin_id}:\s*\{{[^}}]*\}}", block).group(0)
            self.assertIn('Derived', entry)
            self.assertNotIn('Official', entry)


class TestImagesLoadLazily(unittest.TestCase):
    # Nov 2026: both image builders assigned src before loading='lazy', so the
    # browser fetched all ~66 product images (~12 MB) on first load, including
    # on mobile. Lazy loading only works when it is set before src.
    def test_lazy_loading_is_set_before_src(self):
        for var in ('thumb', 'image'):
            for match in re.finditer(rf"\b{var}\.src = ", INDEX):
                before = INDEX[max(0, match.start() - 400):match.start()]
                after = INDEX[match.end():match.end() + 400]
                self.assertIn(f"{var}.loading = 'lazy'", before,
                              f'{var}.src is assigned before {var}.loading')
                self.assertNotIn(f"{var}.loading = ", after,
                                 f'{var}.loading is set after {var}.src')
