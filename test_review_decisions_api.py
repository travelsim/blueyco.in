import importlib.util
import json
import os
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "review_decisions", os.path.join(_ROOT, "api", "review-decisions.py")
)
review_decisions = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(review_decisions)


class TestValidateReviewDecisions(unittest.TestCase):
    def test_accepts_documented_decision_values(self):
        payload = {
            "kind": "bluey-outlier-review",
            "decisions": [
                {"listing_id": "147296508393", "decision": "recent-only"},
                {"listing_id": "manual-e8b79837323098d0", "decision": "publish-value"},
            ],
        }
        fields, error = review_decisions.validate(payload)
        self.assertIsNone(error)
        self.assertEqual(len(fields["decisions"]), 2)
        self.assertEqual(fields["source"], "blueyco.in/outlier-review")

    def test_rejects_wrong_kind_and_invalid_decision(self):
        fields, error = review_decisions.validate(
            {"kind": "other", "decisions": [{"listing_id": "1", "decision": "recent-only"}]}
        )
        self.assertIsNone(fields)
        self.assertIn("kind", error)

        fields, error = review_decisions.validate(
            {
                "kind": "bluey-outlier-review",
                "decisions": [{"listing_id": "1", "decision": "hide-everything"}],
            }
        )
        self.assertIsNone(fields)
        self.assertIn("Invalid decision", error)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestDeliverReviewDecisions(unittest.TestCase):
    def test_deliver_posts_pipeline_to_existing_kv(self):
        record = {
            "kind": "bluey-outlier-review",
            "decisions": [{"listing_id": "147296508393", "decision": "recent-only"}],
        }
        response = _Response()
        response.read = lambda: json.dumps([{"result": 1}, {"result": "OK"}]).encode()

        with mock.patch.dict(
            os.environ,
            {"KV_REST_API_URL": "https://redis.example", "KV_REST_API_TOKEN": "token"},
            clear=False,
        ), mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            stored, error = review_decisions.deliver(record)

        self.assertTrue(stored)
        self.assertIsNone(error)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://redis.example/pipeline")
        self.assertEqual(request.headers["Authorization"], "Bearer token")
        commands = json.loads(request.data)
        self.assertEqual(commands[0][0], "RPUSH")
        self.assertEqual(commands[0][1], review_decisions.QUEUE_KEY)
        self.assertEqual(json.loads(commands[0][2])["decisions"], record["decisions"])
        self.assertEqual(commands[1], ["EXPIRE", review_decisions.QUEUE_KEY, str(90 * 24 * 60 * 60)])


if __name__ == "__main__":
    unittest.main()
