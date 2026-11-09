"""Exercise updater activation and multipart upload against a local mock endpoint."""
import sys, threading, tempfile
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from ota_update import upload_http, check_image
requests = []
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        requests.append((self.path, dict(self.headers), body))
        self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
    def log_message(self, *args): pass
server = HTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
try:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / 'firmware.bin'
        data = bytearray(64); data[0] = 0xe9; data[12] = 9; p.write_bytes(data)
        check_image(p)
        upload_http(f'127.0.0.1:{server.server_port}', 'TestToken1234567', p)
        assert [r[0] for r in requests] == ['/ota/arm', '/ota/upload']
        assert requests[1][1]['X-Image-Size'] == '64'
        assert bytes(data) in requests[1][2]
        assert b'filename="firmware.bin"' in requests[1][2]
        data[12] = 0; p.write_bytes(data)
        try: check_image(p)
        except ValueError: pass
        else: raise AssertionError('Wrong chip accepted')
finally:
    server.shutdown(); server.server_close(); thread.join()
print('PASS: HTTP activation, multipart payload, image size, wrong-chip rejection')
