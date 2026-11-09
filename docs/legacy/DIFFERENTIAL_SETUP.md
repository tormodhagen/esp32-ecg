# Differential ADC and input-voltage calibration

Replace src/main.cpp and platformio.ini, keeping your existing src/ota_config.h
and its credentials/token. Target is XIAO ESP32-S3: SDA D4/GPIO5, SCL D5/GPIO6,
ALERT/RDY D3/GPIO4. ADS1115 measures AIN0 (signal) minus AIN1 (reference).
GAIN_ONE remains unchanged: 125 uV per signed ADC count. Both input pins must
remain within their allowed absolute voltage range; differential mode does not
permit negative pin voltages relative to GND.

Flash via USB initially when changing board or partitions. OTA image validation
now accepts ESP32-S3, chip ID 9. Build environment stays named esp32dev.

Copy the Python files to your project. Rebuild executables using build_apps.ps1
if needed. Existing ui_theme.py, ecg_signal.py and ecg_ble.py are required.

Input voltage toggle scales plotted ADC volts by 1000 / analog gain. Set total
analog gain manually or calibrate; default 1 is a placeholder, not calibrated.
Calibration uses up to 20 seconds of raw samples and requires at least 5 seconds
and 5 cycles. Inject a known sine at the frontend input and enter its frequency
and peak-to-peak amplitude. 5 mV peak means 10 mV peak-to-peak. Wait for startup
and connection transients to settle before calibration. Gain is frequency-dependent
because the analog filters are included. Calibration fits a sine plus DC and linear
drift; residual above 10% is rejected, but this does not guarantee absence of all
clipping or distortion. Gain is stored locally when accepted or on clean exit.

Raw recording CSV voltage_V and raw columns remain ADC measurements and are not
rescaled. Audio thresholds and BPM detection remain in ADC units. Old single-ended
recordings retain their DC offset even if input-voltage scaling is enabled.

Firmware compilation/hardware flashing and Windows executable packaging are not
verified in this environment. Python calibration and GUI checks are performed.
