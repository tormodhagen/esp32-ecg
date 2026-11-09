from pathlib import Path
source=(Path(__file__).resolve().parents[1]/'firmware/src/web_mode.cpp').read_text()
section=source[source.index(' http.handleClient();'):]
assert section.index('now=millis();') < section.index('now-armAt>300000')
assert ((1000-1001)&0xffffffff)>300000  # former failure
assert ((1002-1001)&0xffffffff)<300000  # refreshed clock
assert ((2-0xfffffff0)&0xffffffff)==18  # normal rollover
print('PASS: HTTP arming clock refresh precedes expiry check')
