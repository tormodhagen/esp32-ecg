"""Regenerate the compile-time web assets after editing web/ files."""
from pathlib import Path
root=Path(__file__).resolve().parent
assets=[('PORTAL_HTML','portal.html'),('MONITOR_HTML','monitor.html'),('APP_JS','app.js'),('WORKER_JS','analysis-worker.js')]
text='#pragma once\n#include <Arduino.h>\n'
for name,file in assets:
 data=(root/'web'/file).read_text(encoding='utf-8')
 assert ')ECGWEB"' not in data
 text+=f'const char {name}[] PROGMEM = R"ECGWEB({data})ECGWEB";\n'
(root/'src/web_assets.h').write_text(text,encoding='utf-8')
