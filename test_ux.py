import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
INDEX = (ROOT / 'index.html').read_text(encoding='utf-8')

# Comments legitimately mention alert()/confirm() when explaining what was
# removed, so assertions about live code must ignore them.
INDEX_NO_COMMENTS = re.sub(r'/\*.*?\*/', '', INDEX, flags=re.S)
INDEX_NO_COMMENTS = re.sub(r'(?m)^\s*//.*$', '', INDEX_NO_COMMENTS)
INDEX_NO_COMMENTS = re.sub(r'(?<![:\w])//[^\n]*', '', INDEX_NO_COMMENTS)


class TestNoBlockingDialogs(unittest.TestCase):
    def test_no_alert_dialogs_remain(self):
        # alert() froze the whole page on every add-to-cart and after every
        # checkout/lead attempt. Feedback is now delivered by toasts.
        self.assertNotIn('alert(', INDEX_NO_COMMENTS)

    def test_no_confirm_dialog_remainder(self):
        assert 'confirm(' not in INDEX_NO_COMMENTS, 'blocking confirm() still present'
        self.assertIn("resetCollection._timer", INDEX)

    def test_toast_exists_and_is_a_live_region(self):
        self.assertIn('function toast(message, kind)', INDEX)
        self.assertIn("setAttribute('aria-live', 'polite')", INDEX)
        self.assertIn('#toast-host', INDEX)
        self.assertIn('.toast-success', INDEX)


class TestKeyboardAndScreenReader(unittest.TestCase):
    def test_visible_focus_ring_exists(self):
        self.assertIn(':focus-visible', INDEX)
        self.assertIn('outline: 3px solid var(--orange)', INDEX)

    def test_no_clickable_div_stands_in_for_a_control(self):
        # Only the design-modal backdrop may remain a clickable div: it is a
        # presentational scrim, not a control.
        clickable_divs = re.findall(r'<div[^>]*onclick=', INDEX)
        self.assertEqual(len(clickable_divs), 1, clickable_divs)
        idx = INDEX.find('<div id="design-modal" onclick=')
        self.assertGreater(idx, 0)

    def test_dialogs_are_labelled(self):
        self.assertIn('role="dialog"', INDEX)
        self.assertIn('aria-modal="true"', INDEX)
        self.assertIn('aria-labelledby="design-modal-title"', INDEX)
        self.assertIn('aria-label="Shopping cart"', INDEX)

    def test_controls_are_not_double_labelled(self):
        for tag in re.findall(r'<(?:input|select|textarea)\b[^>]*>', INDEX):
            self.assertLessEqual(tag.count('aria-label='), 1, tag[:120])

    def test_form_controls_are_labelled(self):
        for control in ('series-filter', 'type-filter', 'owned-filter', 'search-input', 'sort-select'):
            self.assertRegex(
                INDEX,
                r'<input\b[^>]*id="%s"[^>]*aria-label=' % control
                if control == 'search-input' else
                r'<select\b[^>]*id="%s"[^>]*aria-label=' % control,
                control,
            )

    def test_cart_count_announces_to_screen_readers(self):
        self.assertIn('id="cart-status"', INDEX)
        self.assertIn('role="status"', INDEX)

    def test_lead_form_has_an_alert_region(self):
        self.assertIn('id="design-error"', INDEX)
        self.assertIn('role="alert"', INDEX)


class TestEscapeKey(unittest.TestCase):
    def test_escape_closes_overlays(self):
        self.assertIn("if (e.key === 'Escape') {", INDEX)
        self.assertIn('hideCart();', INDEX)
        self.assertIn('hideDesignModal();', INDEX)


class TestOwnedFilteringIsReal(unittest.TestCase):
    def test_owned_filter_option_exists(self):
        self.assertIn('id="owned-filter"', INDEX)
        self.assertIn('<option value="owned">', INDEX)

    def test_apply_frame_filters_honours_owned_selection(self):
        self.assertIn('function applyFrameFilters()', INDEX)
        self.assertIn("ownedVal !== 'owned'", INDEX)

    def test_frame_owned_cards_are_marked(self):
        self.assertIn("card.className = 'frame-card'", INDEX)
        self.assertIn('frame-owned', INDEX)
        self.assertIn('In your collection', INDEX)

    def test_frame_the_ones_i_own_no_longer_alerts(self):
        idx = INDEX.find('function frameOwnedCoins()')
        seg = INDEX[idx:idx + 900]
        self.assertNotIn('alert(', seg)
        self.assertIn('applyFrameFilters()', seg)


class TestEmptyStates(unittest.TestCase):
    def test_shop_grid_has_an_empty_state(self):
        self.assertIn('empty-state', INDEX)
        self.assertIn('Nothing to show', INDEX)

    def test_empty_state_explains_the_owned_case(self):
        self.assertIn('Tick off some coins in the dashboard', INDEX)


class TestResponsive(unittest.TestCase):
    def test_has_breakpoints_beyond_the_single_small_phone_one(self):
        widths = {int(w) for w in re.findall(r'@media \(max-width: (\d+)px\)', INDEX)}
        self.assertTrue({540, 640, 900}.issubset(widths), widths)

    def test_reduced_motion_is_respected(self):
        self.assertIn('prefers-reduced-motion', INDEX)


class TestCartBadgeReflectsState(unittest.TestCase):
    def test_cart_count_updates_the_badge_not_the_console(self):
        idx = INDEX.find('function updateCartCount()')
        seg = INDEX[idx:idx + 700]
        self.assertIn("document.getElementById('cart-count')", seg)
        self.assertNotIn('console.log', seg)

    def test_badge_is_hidden_when_empty(self):
        idx = INDEX.find('function updateCartCount()')
        seg = INDEX[idx:idx + 700]
        self.assertIn('badge.hidden = cart.length === 0', seg)


class TestHonestCopy(unittest.TestCase):
    def test_meta_description_coin_count_matches_the_catalogue(self):
        ids = re.findall(r"\{\s*id:\s*'([^']+)'\s*,\s*series:", INDEX)
        count = len(ids)
        self.assertGreater(count, 0)
        self.assertEqual(len(set(ids)), count)
        desc = re.search(r'<meta name="description" content="([^"]+)"', INDEX).group(1)
        self.assertIn(f'{count} Bluey collectibles, including coins and stamps', desc)

    def test_static_market_ranges_are_not_presented_as_current_market_facts(self):
        self.assertNotIn('Market ${coin.marketLow}', INDEX)
        self.assertNotIn('market-range', INDEX)

    def test_no_unverified_social_proof_claims(self):
        hero = INDEX.split('class="hero"')[1].split('</section>')[0]
        self.assertNotIn('trusted by serious collectors', hero.lower())

    def test_no_stale_48_frame_claim(self):
        self.assertNotIn('48 Frames', INDEX)


class TestClutterReduction(unittest.TestCase):
    def test_navigation_has_one_frames_destination(self):
        nav = INDEX.split('<header class="nav" id="site-header">')[1].split('</header>')[0]
        self.assertEqual(nav.count('href="#shop"'), 1)
        self.assertIn('>Collection<', nav)
        self.assertIn('>Price Guide<', nav)

    def test_collection_list_is_grouped_filterable_and_searchable(self):
        self.assertIn('id="dash-search"', INDEX)
        for name in ('all', 'owned', 'missing', 'wishlist'):
            self.assertIn(f'data-filter="{name}"', INDEX)
        self.assertIn('function toggleDashboardCoins()', INDEX)
        self.assertIn('function setDashFilter(', INDEX)
        self.assertIn("'dash-group'", INDEX)
        # no stale hardcoded totals in the markup
        self.assertNotIn('0 / 53', INDEX)
        self.assertNotIn('Show all 60 tracked products', INDEX)

    def test_dashboard_refreshes_when_prices_arrive(self):
        body = INDEX.split('async function loadPrices()')[1].split('\n}\n')[0]
        self.assertIn('renderDashboard()', body)

    def test_shop_defaults_to_photographed_frames(self):
        self.assertIn('let frameCatalogueExpanded = false', INDEX)
        self.assertIn('matching.filter(frame => frame.image)', INDEX)
        self.assertIn('function toggleFrameCatalogue()', INDEX)
        self.assertIn('featured frames', INDEX)

    def test_price_cards_progressively_disclose_detail(self):
        # The card redesign removed the details toggle and sparkline; assert the cleaned-up card instead.
        self.assertNotIn('card-details-toggle', INDEX)
        self.assertNotIn('series-dot', INDEX)
        self.assertNotIn('sold-search-link', INDEX)

    def test_cart_count_has_one_source_of_truth(self):
        self.assertEqual(INDEX.count('function updateCartCount()'), 1)


class TestMobileHeaderNoOverlap(unittest.TestCase):
    def test_hamburger_toggle_exists_and_controls_nav(self):
        self.assertIn('id="nav-toggle"', INDEX)
        self.assertIn('aria-controls="site-nav"', INDEX)
        self.assertIn("header.classList.toggle('nav-open')", INDEX)

    def test_nav_links_hidden_on_mobile_shown_on_desktop(self):
        self.assertIn('.nav-links {', INDEX)
        self.assertIn('display: none;', INDEX)
        self.assertIn('.nav.nav-open .nav-links { display: flex; }', INDEX)
        self.assertIn('@media (min-width: 720px)', INDEX)

    def test_header_inner_wraps_without_overlapping(self):
        self.assertIn('.nav-inner { flex-wrap: wrap;', INDEX)

    def test_skip_link_exists(self):
        self.assertIn('class="skip-link"', INDEX)
        self.assertIn('href="#dashboard"', INDEX)

    def test_cart_drawer_fits_small_phones(self):
        self.assertIn('width: min(380px, 100vw)', INDEX)

    def test_tap_targets_meet_44px(self):
        self.assertIn('.tab-btn, .subtle-button, .btn-add, .btn-primary { min-height: 44px; }', INDEX)
        self.assertIn('.cart-button { min-width: 44px; min-height: 44px;', INDEX)


class TestSeoAeo(unittest.TestCase):
    def test_canonical_and_og_url_are_static(self):
        self.assertIn('<link rel="canonical" id="canonical-url" href="https://blueyco.in/">', INDEX)
        self.assertIn('<meta property="og:url" id="og-url" content="https://blueyco.in/">', INDEX)

    def test_social_images_present(self):
        self.assertIn('og:image', INDEX)
        self.assertIn('twitter:image', INDEX)

    def test_faq_section_visible_and_matches_json_ld(self):
        self.assertIn('id="faq"', INDEX)
        self.assertIn('How many official Bluey coins are there?', INDEX)
        self.assertIn('"@type": "FAQPage"', INDEX)
        self.assertIn('What is a Bluey Dollarbuck worth?', INDEX)

    def test_main_landmark_wraps_content(self):
        self.assertIn('<main id="main-content">', INDEX)
        self.assertIn('</main>', INDEX)

    def test_chart_js_is_deferred(self):
        self.assertIn('defer src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js', INDEX)


if __name__ == '__main__':
    unittest.main()


class TestAuthUiPolish(unittest.TestCase):
    def test_swap_note_follows_sign_in_state(self):
        self.assertIn('id="swap-local-note"', INDEX)
        self.assertIn("getElementById('swap-local-note')", INDEX)
        self.assertIn('syncs across devices', INDEX)

    def test_successful_sync_reports_time(self):
        self.assertIn('toLocaleTimeString', INDEX)
        self.assertIn("'Synced ' + new Date()", INDEX)

    def test_google_button_is_centered_and_constrained(self):
        self.assertIn('#google-signin { display: flex; justify-content: center; }', INDEX)
        self.assertIn('#google-signin iframe { max-width: 100%; }', INDEX)
