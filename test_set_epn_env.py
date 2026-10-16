import builtins
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from urllib.error import HTTPError

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(REPO_ROOT, 'scripts', 'set_epn_env.py')
TOKEN_PATH = '/Users/jameslove/.render_token'
PLACEHOLDER = 'CAMPAIGN_ID = "YOUR_EPN_CAMPAIGN_ID"'
PUT_URL = 'https://api.render.com/v1/services/srv-d8ah7rmgvqtc73csctng/env-vars'
DEPLOY_URL = 'https://api.render.com/v1/services/srv-d8ah7rmgvqtc73csctng/deploys'
DEPLOY_JSON = json.dumps({'id': 'dep-1', 'status': 'created'}).encode()


class FakeResponse:
    def __init__(self, status=200, body=b''):
        self.status = status
        self._body = body

    def read(self):
        return self._body


def http_error(code, body):
    return HTTPError(PUT_URL, code, 'error', {}, io.BytesIO(body))


def offline(testcase):
    """Fail any test that reaches the network instead of mocking it."""
    for target in ('urllib.request.urlopen', 'socket.create_connection'):
        guard = patch(target, side_effect=AssertionError(f'live network call attempted via {target}'))
        guard.start()
        testcase.addCleanup(guard.stop)


class SetEpnEnvTests(unittest.TestCase):
    """Runs the real script source with the Render token and HTTP layer stubbed.

    The script hard-codes a placeholder campaign ID that exits before any request.
    Request-path tests compile the same source with only that placeholder replaced,
    under the real file name, so coverage is recorded against scripts/set_epn_env.py.
    """

    def setUp(self):
        offline(self)
        with open(SCRIPT_PATH, encoding='utf-8') as stream:
            self.source = stream.read()

    def script_source(self, campaign_id=None):
        if campaign_id is None:
            return self.source
        # Same line count, so coverage line numbers still match the real file.
        self.assertEqual(self.source.count(PLACEHOLDER), 1)
        return self.source.replace(PLACEHOLDER, f'CAMPAIGN_ID = "{campaign_id}"')

    def run_script(self, source, responses=(), token='test-token\n', token_error=None):
        real_open = builtins.open
        opened = []

        def fake_open(file, *args, **kwargs):
            if file == TOKEN_PATH:
                opened.append(file)
                if token_error is not None:
                    raise token_error
                return io.StringIO(token)
            return real_open(file, *args, **kwargs)

        url_patch = patch('urllib.request.urlopen', side_effect=list(responses))
        urlopen = url_patch.start()
        self.addCleanup(url_patch.stop)
        self.last_urlopen = urlopen

        stdout = io.StringIO()
        exit_code = None
        code = compile(source, SCRIPT_PATH, 'exec')
        with patch('builtins.open', side_effect=fake_open), redirect_stdout(stdout):
            try:
                exec(code, {'__name__': '__main__', '__file__': SCRIPT_PATH})
            except SystemExit as exit_info:
                exit_code = exit_info.code
        return {'urlopen': urlopen, 'stdout': stdout.getvalue(), 'exit': exit_code, 'opened': opened}

    def test_success_sets_campaign_id_then_triggers_a_deploy(self):
        result = self.run_script(self.script_source('1234567'), responses=[
            FakeResponse(200), FakeResponse(201, DEPLOY_JSON)])
        put_req, deploy_req = [c.args[0] for c in result['urlopen'].call_args_list]

        self.assertEqual(put_req.get_method(), 'PUT')
        self.assertEqual(put_req.full_url, PUT_URL)
        self.assertEqual(json.loads(put_req.data), {'EPN_CAMPAIGN_ID': {'value': '1234567'}})
        self.assertEqual(put_req.get_header('Authorization'), 'Bearer test-token')

        self.assertEqual(deploy_req.get_method(), 'POST')
        self.assertEqual(deploy_req.full_url, DEPLOY_URL)
        self.assertEqual(json.loads(deploy_req.data), {'clearCache': 'do_not_clear'})
        self.assertEqual(deploy_req.get_header('Authorization'), 'Bearer test-token')

        self.assertEqual([c.kwargs['timeout'] for c in result['urlopen'].call_args_list], [15, 30])
        self.assertIsNone(result['exit'])
        self.assertIn('Status: 200', result['stdout'])
        self.assertIn('EPN_CAMPAIGN_ID set successfully!', result['stdout'])
        self.assertIn('Deploy triggered: dep-1 - status: created', result['stdout'])

    def test_token_is_read_from_the_render_token_file_and_never_printed(self):
        result = self.run_script(self.script_source('1234567'), responses=[
            FakeResponse(200), FakeResponse(201, DEPLOY_JSON)], token='super-secret-value\n')
        self.assertEqual(result['opened'], [TOKEN_PATH])
        self.assertNotIn('super-secret-value', result['stdout'])

    def test_token_file_whitespace_is_stripped_from_the_header(self):
        result = self.run_script(self.script_source('1234567'), responses=[
            FakeResponse(200), FakeResponse(201, DEPLOY_JSON)], token='  test-token \n')
        put_req = result['urlopen'].call_args_list[0].args[0]
        self.assertEqual(put_req.get_header('Authorization'), 'Bearer test-token')

    def test_put_http_error_is_reported_and_the_deploy_still_runs(self):
        result = self.run_script(self.script_source('1234567'), responses=[
            http_error(401, b'bad token'), FakeResponse(201, DEPLOY_JSON)])
        self.assertEqual(result['urlopen'].call_count, 2)
        self.assertIn('HTTP 401: bad token', result['stdout'])
        self.assertNotIn('set successfully', result['stdout'])
        self.assertIn('Deploy triggered: dep-1', result['stdout'])

    def test_put_network_error_is_reported_and_the_deploy_still_runs(self):
        result = self.run_script(self.script_source('1234567'), responses=[
            OSError('connection reset'), FakeResponse(201, DEPLOY_JSON)])
        self.assertEqual(result['urlopen'].call_count, 2)
        self.assertIn('Error: connection reset', result['stdout'])
        self.assertIn('Deploy triggered: dep-1', result['stdout'])

    def test_deploy_http_error_is_reported(self):
        result = self.run_script(self.script_source('1234567'), responses=[
            FakeResponse(200), http_error(500, b'busy')])
        self.assertIn('EPN_CAMPAIGN_ID set successfully!', result['stdout'])
        self.assertIn('Deploy HTTP 500: busy', result['stdout'])
        self.assertNotIn('Deploy triggered', result['stdout'])

    def test_deploy_network_error_is_reported(self):
        result = self.run_script(self.script_source('1234567'), responses=[
            FakeResponse(200), OSError('no route to host')])
        self.assertIn('Deploy error: no route to host', result['stdout'])

    def test_both_requests_failing_reports_both_and_exits_normally(self):
        result = self.run_script(self.script_source('1234567'), responses=[
            http_error(403, b'forbidden'), http_error(403, b'forbidden')])
        self.assertIsNone(result['exit'])
        self.assertIn('HTTP 403: forbidden', result['stdout'])
        self.assertIn('Deploy HTTP 403: forbidden', result['stdout'])

    def test_unchanged_placeholder_exits_1_without_any_request(self):
        result = self.run_script(self.script_source(), responses=[])
        self.assertEqual(result['exit'], 1)
        result['urlopen'].assert_not_called()
        self.assertIn('Campaign ID not provided yet.', result['stdout'])
        self.assertIn('EPN_CAMPAIGN_ID=1234567 python3 set_epn_env.py', result['stdout'])

    def test_missing_token_file_fails_before_any_request(self):
        with self.assertRaises(FileNotFoundError):
            self.run_script(self.script_source('1234567'), responses=[],
                            token_error=FileNotFoundError(TOKEN_PATH))
        self.last_urlopen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
