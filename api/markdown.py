import os
from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        llms_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'llms.txt')
        try:
            with open(llms_path, 'rb') as f:
                data = f.read()
        except FileNotFoundError:
            data = b"# Bluey Coin Tracker\n\nLive pricing and catalogue data for Australian Bluey commemorative coins.\n"

        self.send_response(200)
        self.send_header('Content-Type', 'text/markdown; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('x-markdown-tokens', '1250')
        self.send_header('Vary', 'Accept')
        self.send_header('Cache-Control', 'public, max-age=3600')
        self.end_headers()
        self.wfile.write(data)
