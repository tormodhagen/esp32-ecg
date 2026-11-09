# ECG desktop applications

Run ECG-Monitor for USB/BLE viewing. The plotted voltage unit is mV (0.001 mV = 1 µV). CSV voltage remains raw ADC volts; gain and calibration metadata are recorded in the first comment line.

Run ECG-Updater and select your PlatformIO project directory. Leave Wi-Fi host empty for BLE-triggered ArduinoOTA, or enter the device IP / http://ecg.local for HTTP updating on the new connected firmware. Retain your existing src/ota_config.h and its OTA_TOKEN.

To rebuild, run build_apps.ps1 on Windows. It prefers your project's .venv Python if available. Otherwise install Python 3.12 or supply an installed compatible interpreter with -Python "C:\path\to\python.exe". Builds require Internet access for dependencies. Full firmware installation details are in the package README.md.
