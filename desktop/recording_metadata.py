"""CSV v2: ADC volts remain authoritative; calibration is explicit metadata."""
import json
from datetime import datetime, timezone

def snapshot(gain, enabled, calibration, display_filter, source):
    return dict(format='ecg-csv-v2', created_utc=datetime.now(timezone.utc).isoformat(),
                voltage_column='voltage_V', voltage_units='V', voltage_reference='ADC differential AIN0-AIN1',
                analog_gain_v_per_v=float(gain), gain_compensation_enabled=bool(enabled),
                gain_applied_to_voltage_column=False, input_voltage_formula='voltage_V / analog_gain_v_per_v',
                adc_lsb_V=0.000125, adc_pga='GAIN_ONE +/-4.096V',
                display_filter=display_filter, filter_applied_to_voltage_column=False,
                calibration=calibration, source=source)

def write_header(stream, metadata):
    stream.write('# ecg_metadata=' + json.dumps(metadata, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n')

def read_header(path):
    with open(path, encoding='utf-8-sig') as stream:
        for line in stream:
            if line.startswith('# ecg_metadata='):
                result = json.loads(line.split('=', 1)[1])
                gain = float(result.get('analog_gain_v_per_v', 1))
                if not .001 <= gain <= 1000000: raise ValueError('Invalid gain in recording header')
                return result
            if line.strip() and not line.startswith('#'): break
    return None
