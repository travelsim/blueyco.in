import json
import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
VERCEL_CONFIG = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


class TestVercelAnalyticsInstrumentation(unittest.TestCase):
    def test_uses_same_origin_vercel_scripts_without_plausible(self):
        self.assertIn('src="/_vercel/insights/script.js"', INDEX)
        self.assertIn('src="/_vercel/speed-insights/script.js"', INDEX)
        self.assertNotIn("plausible.io", INDEX.lower())

    def test_custom_events_are_allowlisted_and_have_no_properties(self):
        event_names = set(re.findall(r"trackEvent\('([^']+)'\)", INDEX))
        self.assertEqual(
            event_names,
            {
                "Search",
                "Where to Buy",
                "Add to Cart",
                "Custom Frame Submit Attempt",
                "Sign In Open",
                "Sign In Magic Requested",
                "Sign In Complete",
                "Sign Out",
                "Collection Remote Synced",
            },
        )
        self.assertIn("window.va('event', { name });", INDEX)
        self.assertNotIn("trackEvent('Purchase')", INDEX)

    def test_analytics_events_set_matches_all_call_sites_and_contains_no_pii(self):
        match = re.search(r"const ANALYTICS_EVENTS = new Set\(\[\s*([\s\S]*?)\s*\]\);", INDEX)
        self.assertIsNotNone(match)
        set_events = set(re.findall(r"'([^']+)'", match.group(1)))
        call_events = set(re.findall(r"trackEvent\('([^']+)'\)", INDEX))
        self.assertEqual(set_events, call_events)
        for name in set_events:
            self.assertFalse(re.search(r"@|token|user_id|email|cookie", name, re.IGNORECASE))


class TestVercelDeploymentConfiguration(unittest.TestCase):
    def test_python_runtime_is_auto_detected_with_duration_preserved(self):
        function_config = VERCEL_CONFIG["functions"]["api/**/*.py"]
        self.assertEqual(function_config, {"maxDuration": 10})

    def test_spa_fallback_excludes_api_and_vercel_platform_routes(self):
        self.assertNotIn("routes", VERCEL_CONFIG)
        self.assertEqual(
            VERCEL_CONFIG["rewrites"],
            [
                {
                    "source": "/((?!api(?:/|$)|_vercel(?:/|$)).*)",
                    "destination": "/index.html",
                },
            ],
        )

    def test_prototype_app_route_redirects_to_the_real_dashboard(self):
        self.assertEqual(
            VERCEL_CONFIG["redirects"],
            [{"source": "/app", "destination": "/", "permanent": True}],
        )
        self.assertFalse((ROOT / "app.html").exists())

    def test_python_312_is_pinned_in_project_metadata(self):
        self.assertEqual(PYPROJECT["project"]["requires-python"], "~=3.12.0")


if __name__ == "__main__":
    unittest.main()
