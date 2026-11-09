import os, subprocess, sys, tempfile, threading
from pathlib import Path
from http.server import HTTPServer,BaseHTTPRequestHandler
root=Path(__file__).resolve().parents[1]
requests=[]
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length',0)));requests.append(self.path)
        self.send_response(200);self.end_headers();self.wfile.write(b'Firmware verified')
    def log_message(self,*args):pass
server=HTTPServer(('127.0.0.1',0),Handler)
t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
try:
    with tempfile.TemporaryDirectory() as folder:
        p=Path(folder);image=bytearray(64);image[0]=0xe9;image[12]=9;(p/'firmware.bin').write_bytes(image)
        env=os.environ.copy();env['ECG_OTA_TOKEN']='TestToken1234567';env['ECG_OTA_LOG']=str(p/'worker.log')
        result=subprocess.run([sys.executable,str(root/'desktop/main.py'),'--ota-worker','--http-upload','--firmware',str(p/'firmware.bin'),'--host',f'127.0.0.1:{server.server_port}'],env=env,capture_output=True,timeout=15)
        assert result.returncode==0,(result.stderr,(p/'worker.log').read_text())
        assert requests==['/ota/arm','/ota/upload']
        assert 'Upload reported successful' in (p/'worker.log').read_text()
        assert env['ECG_OTA_TOKEN'] not in (p/'worker.log').read_text()
finally:
    server.shutdown();server.server_close();t.join()
print('PASS: same-entry-point OTA subprocess, logfile output, HTTP transfer')
