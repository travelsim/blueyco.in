import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
INDEX = (ROOT / 'index.html').read_text(encoding='utf-8')
FRAMES_DIR = ROOT / 'frames'


def photo_map():
    block = INDEX.split('const FRAME_PHOTOS = {')[1].split('};')[0]
    return dict(re.findall(r"'(s[123]_[a-z0-9_]+)':\s*\{\s*file:\s*'([^']+)'", block))


class TestFramePhotosExist(unittest.TestCase):
    def test_every_mapped_photo_is_on_disk(self):
        photos = photo_map()
        self.assertTrue(photos, 'no FRAME_PHOTOS mapping found')
        for coin_id, filename in photos.items():
            path = FRAMES_DIR / filename
            self.assertTrue(path.exists(), f'{coin_id} -> {filename} missing')

    def test_no_dead_placeholder_paths_remain(self):
        # The old code built /frames/<coinId>.jpg, which never existed.
        self.assertNotIn('`/frames/${coin.id}.jpg`', INDEX)
        self.assertNotIn('Image coming soon', INDEX)

    def test_every_file_in_frames_is_mapped_to_something(self):
        mapped = set(photo_map().values())
        on_disk = {p.name for p in FRAMES_DIR.glob('*.jpg')}
        self.assertEqual(on_disk - mapped, set(), 'orphan photo files')

    def test_filenames_are_self_describing(self):
        # Two files were previously named for the wrong subject, which made the
        # shop misrepresent the product.
        names = ' '.join(photo_map().values()).lower()
        for word in ('blister', 'pin-cover', 'tube-set', 'proof-capsule', 'privy'):
            self.assertIn(word, names)

    def test_photos_are_reasonably_sized(self):
        for name in photo_map().values():
            size = (FRAMES_DIR / name).stat().st_size
            self.assertGreater(size, 50_000, f'{name} suspiciously small ({size} bytes)')


class TestFrameCardRendering(unittest.TestCase):
    def test_card_renders_a_real_image_when_available(self):
        self.assertIn('<img class="frame-photo"', INDEX)
        self.assertIn('loading="lazy"', INDEX)
        self.assertIn('decoding="async"', INDEX)
        # Intrinsic dimensions stop lazy images reflowing the grid.
        self.assertIn('width="640" height="400"', INDEX)

    def test_images_carry_descriptive_alt_text(self):
        self.assertIn('alt="${escapeHtml(frame.imageAlt)}"', INDEX)
        block = INDEX.split('const FRAME_PHOTOS = {')[1].split('};')[0]
        alts = re.findall(r"alt:\s*'([^']+)'", block)
        self.assertEqual(len(alts), len(photo_map()))
        for alt in alts:
            self.assertGreater(len(alt), 40, alt)

    def test_missing_photo_says_so_plainly(self):
        self.assertIn('class="frame-nophoto"', INDEX)
        self.assertIn('No photo yet', INDEX)

    def test_alt_text_is_escaped_in_the_template(self):
        # Alt text comes from a static map, but it is interpolated into an
        # innerHTML template literal, so a stray quote would break the markup.
        block = INDEX.split('const FRAME_PHOTOS = {')[1].split('};')[0]
        for alt in re.findall(r"alt:\s*'([^']+)'", block):
            self.assertNotIn('"', alt)


class TestFrameMediaLayout(unittest.TestCase):
    def test_media_box_has_a_fixed_aspect_ratio(self):
        self.assertIn('aspect-ratio: 16 / 10', INDEX)
        self.assertIn('object-fit: cover', INDEX)

    def test_hover_zoom_respects_reduced_motion(self):
        self.assertIn('.frame-card:hover .frame-photo', INDEX)
        self.assertIn('prefers-reduced-motion', INDEX)


class TestFrameCatalogue(unittest.TestCase):
    def test_tube_sets_have_their_own_type(self):
        self.assertIn("type = 'tube'", INDEX)

    def test_frame_count_is_not_hardcoded(self):
        # The shop header used to say "48 frames" regardless of the catalogue.
        self.assertIn("document.getElementById('frame-count').textContent", INDEX)
        idx = INDEX.find('id="frame-count"')
        window = INDEX[max(0, idx - 200):idx + 60]
        self.assertNotIn('>48<', window)


if __name__ == '__main__':
    unittest.main()
