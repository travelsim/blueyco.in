"""Protected Preview-only, read-only Neon connection identity probe.

Requires PREVIEW_DB_PROBE_TOKEN and DATABASE_URL in the deployment environment.
Returns only pass/fail; never emits connection or database metadata values.
"""
import hmac
import os

from http.server import BaseHTTPRequestHandler

EXPECTED_BRANCH = "br-frosty-scene-bk9zs4kg"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        expected_token = os.environ.get("PREVIEW_DB_PROBE_TOKEN", "")
        supplied = self.headers.get("Authorization", "")
        if not expected_token or not hmac.compare_digest(
                supplied, "Bearer " + expected_token):
            self.send_error(404)
            return

        try:
            import psycopg
            conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5,
                                   options="-c default_transaction_read_only=on")
            try:
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute("SELECT current_database(), "
                                "current_setting('neon.branch_id', true)")
                    database_name, branch_id = cur.fetchone()
                conn.rollback()
            finally:
                conn.close()
            # Branch identity is checked using the connection's Neon setting.
            # Keep database name only as a sanity check; neither value is returned.
            passed = database_name == "bluey" and branch_id == EXPECTED_BRANCH
        except Exception:
            passed = False

        body = b'{"pass":true}' if passed else b'{"pass":false}'
        self.send_response(200 if passed else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
