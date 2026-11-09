import sys,io,tempfile,json,csv
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
from recording_metadata import snapshot,write_header,read_header
m=snapshot(431.646,True,{'method':'positive_half_sine','frequency_hz':1,'input_mV_pp':2},'raw','live')
f=io.StringIO();write_header(f,m);f.write('time_s,voltage_V\n0,0.431646\n')
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'ecg.csv';p.write_text(f.getvalue());r=read_header(p)
 assert r['analog_gain_v_per_v']==431.646 and not r['gain_applied_to_voltage_column']
 rows=list(csv.DictReader(x for x in f.getvalue().splitlines() if not x.startswith('#')))
 assert abs(float(rows[0]['voltage_V'])/r['analog_gain_v_per_v']-.001)<1e-12
 p.write_text('time_s,voltage_V\n0,1\n');assert read_header(p) is None
print('PASS: calibration header round-trip, ADC volts unchanged, old CSV compatibility')
