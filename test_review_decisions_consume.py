"""Decision collapse/mapping/record coverage for the publisher consumer.

Fixtures only: no network, no database. Proves latest-wins collapse,
fail-closed mapping (unknown and unmapped values never publish), fetch
failing closed without credentials, and Melbourne upserts with the
older-submission guard.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import review_decisions as rd


def _rec(submitted, *pairs):
    return {
        "kind": "bluey-outlier-review",
        "source": "blueyco.in/outlier-review",
        "submitted_at": submitted,
        "decisions": [{"listing_id": lid, "decision": dec}
                      for lid, dec in pairs],
    }


class TestCollapseRecords(unittest.TestCase):
    def test_latest_submission_wins(self):
        decided, stats = rd.collapse_records([
            _rec("2026-11-24T05:00:00+00:00", ("a", "also-in-value")),
            _rec("2026-11-24T06:00:00+00:00", ("a", "not-valid"),
                 ("b", "keep-pending")),
        ])
        self.assertEqual(decided["a"], ("not-valid", "2026-11-24T06:00:00+00:00"))
        self.assertEqual(decided["b"][0], "keep-pending")
        self.assertEqual(stats["unique_listings"], 2)
        self.assertEqual(stats["duplicate_listings"], 1)
        self.assertEqual(stats["by_decision"]["not-valid"], 1)

    def test_older_resubmission_does_not_win(self):
        decided, _ = rd.collapse_records([
            _rec("2026-11-24T06:00:00+00:00", ("a", "not-valid")),
            _rec("2026-11-24T05:00:00+00:00", ("a", "also-in-value")),
        ])
        self.assertEqual(decided["a"][0], "not-valid")


class TestDispositionFor(unittest.TestCase):
    def test_mapped_values(self):
        self.assertEqual(rd.disposition_for("recent-only")[0], "published")
        self.assertFalse(rd.disposition_for("recent-only")[1])
        self.assertEqual(rd.disposition_for("also-in-value")[0:2],
                        ("published", True))
        self.assertEqual(rd.disposition_for("publish-recent")[0:2], ("published", False))
        self.assertEqual(rd.disposition_for("publish-value")[0:2], ("published", True))
        self.assertEqual(rd.disposition_for("keep-held")[0], "held")
        self.assertEqual(rd.disposition_for("not-valid")[0], "excluded")
        self.assertEqual(rd.disposition_for("keep-pending")[0], "pending-review")

    def test_unmapped_values_queued_hidden_fail_closed(self):
        for value in ("keep-out", "hide-everything", ""):
            action, value_ok, reason = rd.disposition_for(value)
            self.assertEqual(action, "pending-review")
            self.assertTrue(value_ok)
            self.assertIn("fail closed", reason)


class TestFetchFailClosed(unittest.TestCase):
    def test_raises_without_any_credential(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(rd.DecisionFetchError):
                rd.fetch_records()

    def test_raises_on_rejected_api_payload(self):
        import json as _json

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return _json.dumps({"nope": True}).encode()

        import os as _os
        with mock.patch.dict("os.environ",
                             {"REVIEW_QUEUE_READ_TOKEN": "t"}, clear=True), \
            mock.patch("urllib.request.urlopen", return_value=_Resp()):
            with self.assertRaises(rd.DecisionFetchError):
                rd.fetch_records()


class TestRecordMelbourne(unittest.TestCase):
    def test_creates_table_then_upserts_with_older_guard(self):
        seen = []

        def fake_psql(sql):
            seen.append(sql)
            if sql.startswith("CREATE TABLE"):
                return ""
            return "INSERT 0 1"

        with mock.patch("melbourne_drift._ssh_psql", side_effect=fake_psql):
            written = rd.record_melbourne(
                {"a": ("not-valid", "2026-11-24T06:00:00+00:00")})
        self.assertEqual(written, 1)
        self.assertTrue(seen[0].startswith("CREATE TABLE IF NOT EXISTS review_decisions"))
        upsert = seen[1]
        self.assertIn("ON CONFLICT (listing_id) DO UPDATE", upsert)
        self.assertIn("EXCLUDED.submitted_at >= review_decisions.submitted_at", upsert)
        # values are literal-quoted, never interpolated raw
        self.assertIn("'not-valid'", upsert)

    def test_transport_failure_propagates(self):
        with mock.patch("melbourne_drift._ssh_psql",
                        side_effect=RuntimeError("melbourne fetch failed")):
            with self.assertRaises(RuntimeError):
                rd.record_melbourne({"a": ("not-valid", "s")})


if __name__ == "__main__":
    unittest.main()
