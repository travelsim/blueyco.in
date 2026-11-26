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
        if (
            os.environ.get("VERCEL_ENV") != "preview"
            or not expected_token
            or not hmac.compare_digest(supplied, "Bearer " + expected_token)
        ):
            self.send_error(404)
            return

        stage = "driver"
        try:
            import psycopg
            stage = "connect"
            conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)
            try:
                stage = "identity"
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
            if not passed:
                self.log_error("Preview database identity did not match")
        except Exception as exc:
            self.log_error("Preview database check failed at %s (%s)", stage, type(exc).__name__)
            passed = False

        body = b'{"pass":true}' if passed else b'{"pass":false}'
        self.send_response(200 if passed else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
