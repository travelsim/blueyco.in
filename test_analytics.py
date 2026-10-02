import json
import re
import unittest
from pathlib import Path


INDEX = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
VERCEL_CONFIG = json.loads(
    Path(__file__).with_name("vercel.json").read_text(encoding="utf-8")
)


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
            },
        )
        self.assertIn("window.va('event', { name });", INDEX)
        self.assertNotIn("trackEvent('Purchase')", INDEX)

    def test_python_runtime_is_auto_detected_by_vercel(self):
        python_config = VERCEL_CONFIG["functions"]["api/**/*.py"]
        self.assertNotIn("runtime", python_config)
        self.assertEqual(python_config["maxDuration"], 10)


if __name__ == "__main__":
    unittest.main()
