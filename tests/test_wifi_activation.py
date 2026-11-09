"""Test IP activation + existing ArduinoOTA path without Bluetooth or real flash."""
import os, subprocess,sys,tempfile,threading
from pathlib import Path
from http.server import HTTPServer,BaseHTTPRequestHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from ota_update import arm_http
calls=[]
class Handler(BaseHTTPRequestHandler):
    reject=False
    def do_POST(self):
        body=self.rfile.read(int(self.headers.get('Content-Length',0)));calls.append((self.path,body))
        self.send_response(400 if self.reject else 200);self.end_headers()
        self.wfile.write(b'OTA_BAD_SIZE' if self.reject else b'{"armed":true}')
    def log_message(self,*args):pass
server=HTTPServer(('127.0.0.1',0),Handler);t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
try:
    with tempfile.TemporaryDirectory() as d:
        p=Path(d);image=bytearray(64);image[0]=0xe9;image[12]=9;(p/'f.bin').write_bytes(image)
        (p/'espota.py').write_text("import sys\nassert sys.argv[sys.argv.index('-i')+1]=='127.0.0.1'\nprint('MOCK ARDUINO OTA OK')\n")
        env=os.environ.copy();env['ECG_OTA_TOKEN']='TestToken1234567'
        result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'desktop/ota_update.py'),'--host',f'http://127.0.0.1:{server.server_port}','--firmware',str(p/'f.bin'),'--espota',str(p/'espota.py')],capture_output=True,text=True,env=env,timeout=15)
        assert result.returncode==0,(result.stdout,result.stderr)
        assert 'MOCK ARDUINO OTA OK' in result.stdout
        assert calls==[('/ota/arm',b'arm=1')]
        Handler.reject=True
        try:arm_http(f'127.0.0.1:{server.server_port}','TestToken1234567')
        except RuntimeError as e:assert '/ota/arm: HTTP 400' in str(e) and 'OTA_BAD_SIZE' in str(e)
        else:raise AssertionError('HTTP error swallowed')
finally:server.shutdown();server.server_close();t.join()
print('PASS: Wi-Fi activation + ArduinoOTA without BLE; detailed HTTP rejection')
