"""Auth/read coverage for the saved review-decisions reader.

Fixtures only: KV and env are mocked, no network. Proves the GET path
fails closed (no token configured, wrong token, storage down) and serves
stored records with the right token.
"""
import importlib.util
import json
import os
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "review_decisions_under_test",
    os.path.join(_ROOT, "api", "review-decisions.py"),
)
review_decisions = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(review_decisions)


def _queue_payload(items):
    return [{"result": items}]


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _record(lid="abc", decision="also-in-value", submitted="2026-11-24T05:00:00+00:00"):
    return {
        "kind": "bluey-outlier-review",
        "source": "blueyco.in/outlier-review",
        "submitted_at": submitted,
        "decisions": [{"listing_id": lid, "decision": decision}],
    }


def _fake_handler(headers):
    handler = review_decisions.handler.__new__(review_decisions.handler)
    handler.headers = headers
    calls = []
    handler._json = lambda status, payload: calls.append((status, payload))
    return handler, calls


class TestCheckReadAuth(unittest.TestCase):
    def test_denies_when_no_token_configured(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REVIEW_QUEUE_READ_TOKEN", None)
            self.assertFalse(review_decisions.check_read_auth("anything"))

    def test_denies_wrong_or_empty_presented_token(self):
        with mock.patch.dict(os.environ, {"REVIEW_QUEUE_READ_TOKEN": "s3cret"}):
            self.assertFalse(review_decisions.check_read_auth("wrong"))
            self.assertFalse(review_decisions.check_read_auth(""))
            self.assertFalse(review_decisions.check_read_auth(None))

    def test_accepts_exact_token(self):
        with mock.patch.dict(os.environ, {"REVIEW_QUEUE_READ_TOKEN": "s3cret"}):
            self.assertTrue(review_decisions.check_read_auth("s3cret"))


class TestReadQueue(unittest.TestCase):
    def _run(self, payload, env):
        response = _Response(payload)
        with mock.patch.dict(os.environ, env, clear=False), mock.patch(
            "urllib.request.urlopen", return_value=response
        ):
            return review_decisions.read_queue()

    def test_returns_records_oldest_first_and_counts_skipped(self):
        items = [
            json.dumps(_record("a", "recent-only")),
            "not-json{{{",
            json.dumps({"kind": "other", "decisions": []}),
        ]
        records, skipped, error = self._run(
            _queue_payload(items),
            {"KV_REST_API_URL": "https://redis.example",
             "KV_REST_API_TOKEN": "token"},
        )
        self.assertIsNone(error)
        self.assertEqual([r["decisions"][0]["listing_id"] for r in records], ["a"])
        self.assertEqual(skipped, 2)

    def test_fails_closed_without_storage_config(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ("KV_REST_API_URL", "KV_REST_API_TOKEN",
                        "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
                os.environ.pop(key, None)
            records, skipped, error = review_decisions.read_queue()
        self.assertIsNone(records)
        self.assertIsNotNone(error)

    def test_fails_closed_on_transport_error(self):
        with mock.patch.dict(
            os.environ,
            {"KV_REST_API_URL": "https://redis.example",
             "KV_REST_API_TOKEN": "token"},
        ), mock.patch("urllib.request.urlopen",
                      side_effect=OSError("down")):
            records, skipped, error = review_decisions.read_queue()
        self.assertIsNone(records)
        self.assertIsNotNone(error)

    def test_fails_closed_on_error_part(self):
        records, skipped, error = self._run(
            [{"error": "READONLY"}],
            {"KV_REST_API_URL": "https://redis.example",
             "KV_REST_API_TOKEN": "token"},
        )
        self.assertIsNone(records)
        self.assertIsNotNone(error)


class TestHandlerGet(unittest.TestCase):
    def test_get_denies_without_token(self):
        handler, calls = _fake_handler({})
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REVIEW_QUEUE_READ_TOKEN", None)
            handler.do_GET()
        self.assertEqual(calls[0][0], 401)
        self.assertEqual(calls[0][1]["records"], [])

    def test_get_denies_wrong_token(self):
        handler, calls = _fake_handler({"X-Review-Read-Token": "nope"})
        with mock.patch.dict(os.environ, {"REVIEW_QUEUE_READ_TOKEN": "s3cret"}):
            handler.do_GET()
        self.assertEqual(calls[0][0], 401)

    def test_get_serves_records_with_right_token(self):
        payload = _queue_payload([json.dumps(_record("a", "not-valid")),
                                  "junk"])
        response = _Response(payload)
        handler, calls = _fake_handler({"X-Review-Read-Token": "s3cret"})
        with mock.patch.dict(
            os.environ,
            {"REVIEW_QUEUE_READ_TOKEN": "s3cret",
             "KV_REST_API_URL": "https://redis.example",
             "KV_REST_API_TOKEN": "token"}
        ), mock.patch("urllib.request.urlopen", return_value=response):
            handler.do_GET()
        self.assertEqual(calls[0][0], 200)
        self.assertEqual(calls[0][1]["count"], 1)
        self.assertEqual(calls[0][1]["skipped"], 1)
        self.assertEqual(
            calls[0][1]["records"][0]["decisions"][0]["decision"], "not-valid")

    def test_get_502_when_storage_down(self):
        handler, calls = _fake_handler({"X-Review-Read-Token": "s3cret"})
        with mock.patch.dict(
            os.environ,
            {"REVIEW_QUEUE_READ_TOKEN": "s3cret",
             "KV_REST_API_URL": "https://redis.example",
             "KV_REST_API_TOKEN": "token"}
        ), mock.patch("urllib.request.urlopen",
                      side_effect=OSError("down")):
            handler.do_GET()
        self.assertEqual(calls[0][0], 502)
        self.assertEqual(calls[0][1]["records"], [])


if __name__ == "__main__":
    unittest.main()
