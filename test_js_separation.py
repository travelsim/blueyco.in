"""Recent-Sales vs Market-Value separation contract.

_allSoldRecords feeds the Recent Sales display: every verified published
sale, regardless of outlier status. _currentSoldRecords feeds Market Value:
outlier filtering stays. Both functions live in index.html; this test
extracts their real sources plus _filterClientSoldOutliers/_clientPriceBounds
and executes them under node with stubbed data plumbing, so the separation
is proved behaviorally, not by string matching.

Skipped where node is unavailable (CI runs python -m unittest discover
without node); the python suite stays green either way.
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"

WANTED = ("_clientPriceBounds", "_filterClientSoldOutliers",
          "_allSoldRecords", "_currentSoldRecords")


def extract_functions(source):
    found = {}
    for name in WANTED:
        marker = "function %s(" % name
        start = source.find(marker)
        if start < 0:
            raise AssertionError("function %s not found in index.html" % name)
        depth = 0
        i = source.find("{", start)
        for j in range(i, len(source)):
            if source[j] == "{":
                depth += 1
            elif source[j] == "}":
                depth -= 1
                if depth == 0:
                    found[name] = source[start:j + 1]
                    break
        else:
            raise AssertionError("unbalanced braces in %s" % name)
    return found


NODE_HARNESS = """
const day = 24 * 60 * 60 * 1000;
const now = Date.now();
const _normSold = (p, source) => ({price: p.sale_price,
  soldAt: Date.parse(p.date_sold), title: p.title, source: source});
const _validSold = (r) => Number.isFinite(r.price) && r.soldAt > 0;
const _sourceIsFresh = () => true;
const _isClientTitleMismatched = () => false;
const _isSetCatalogItem = () => false;
const coin = {id: 't'};
const mk = (price, daysAgo) => ({sale_price: price,
  date_sold: new Date(now - daysAgo * day).toISOString(),
  title: 'T', listing_id: 'x' + price});
const entry = {ebay: {products: [50, 51, 52, 53, 54, 200].map(
  (p, i) => mk(p, i + 1))}, coinxchange: {}};
const all = _allSoldRecords(entry, coin);
const current = _currentSoldRecords(entry, coin);
console.log(JSON.stringify({
  all: all.map(r => r.price).sort((a, b) => a - b),
  current: current.map(r => r.price).sort((a, b) => a - b),
}));
"""


@unittest.skipIf(shutil.which("node") is None, "node not available")
class TestRecentVsMarketSeparation(unittest.TestCase):
    def test_recent_shows_all_market_filters_outliers(self):
        source = INDEX.read_text(encoding="utf-8")
        funcs = extract_functions(source)
        self.assertEqual(set(funcs), set(WANTED))
        script = "\n".join(funcs[name] for name in WANTED) + NODE_HARNESS
        with tempfile.NamedTemporaryFile("w", suffix=".js",
                                         delete=False) as handle:
            handle.write(script)
            path = handle.name
        proc = subprocess.run(["node", path], capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(result["all"], [50, 51, 52, 53, 54, 200])
        self.assertEqual(result["current"], [50, 51, 52, 53, 54])

    def test_current_still_applies_client_outlier_filter(self):
        source = INDEX.read_text(encoding="utf-8")
        funcs = extract_functions(source)
        self.assertIn("_filterClientSoldOutliers",
                      funcs["_currentSoldRecords"])
        self.assertNotIn("_filterClientSoldOutliers",
                         funcs["_allSoldRecords"])


if __name__ == "__main__":
    unittest.main()
