# ECG Connected update — XIAO ESP32-S3

## Install

This package contains source, not a compiled firmware or Windows EXE. Back up your current project first.

1. Copy the contents of `firmware/` into your PlatformIO project, replacing the matching files. Keep your existing `src/ota_config.h`; this package deliberately does not include it. For a new installation, copy `src/ota_config.example.h` to `src/ota_config.h` and choose your own 16-character alphanumeric token.
2. Copy the contents of `desktop/` into the same project root, alongside `platformio.ini`. This keeps the desktop OTA app's default project lookup correct. Install `requirements-desktop.txt` into your existing Python environment if necessary.
3. Build with `pio run -e esp32dev`. The environment name is retained for compatibility; the board target is **seeed_xiao_esp32s3**. Upload through your existing OTA firmware or USB. If your installed partition layout differs from `min_spiffs.csv`, perform the initial upload through USB.
4. Run `python live_ecg.py` or `python ota_gui.py`. Rebuild Windows apps using the included `build_apps.ps1` if you use EXEs.

Pins: SDA **D4 / GPIO5**, SCL **D5 / GPIO6**, ADS1115 ALERT/RDY **D3 / GPIO4**. ADS address 0x48, differential **A0 minus A1**, GAIN_ONE, 860 SPS. Reference must be connected to A1. Both physical ADC inputs must remain within the ADC's permitted input range.

## Wi-Fi and Bluetooth

Wi-Fi and BLE remain enabled together. On boot, saved Wi-Fi credentials are tried for 30 seconds. If connection fails, or no credentials exist, the board opens `ECG-Setup-XXXX`, password `ecg-setup` (change SETUP_AP_PASSWORD in web_config.h before building if desired).

Join the hotspot and open its captive setup page. Automatic popup behavior depends on the phone/computer; if it does not appear, open **http://192.168.4.1/** manually. Use the detected-network list or enter an SSID manually, then enter its password. The board saves credentials only after connection succeeds. The setup page displays its new IP; the hotspot closes after a 15-second grace period. Join that Wi-Fi and open **http://ecg.local/**, or the displayed IP if name resolution is unavailable. The ESP32 uses 2.4 GHz Wi-Fi.

Alternatively, select **Continue on hotspot** to use the ECG page directly without a router. This choice lasts for the current session; the next boot tries saved Wi-Fi again. Triple rapid power cycles still force the setup hotspot; allow at least eight seconds of stable operation afterward to clear the boot count. A lost router connection also falls back to the hotspot after the reconnect timeout.

Use a normal Safari/Chrome browser for longer recordings and uploads: captive-popup browsers can restrict downloads or close automatically. The monitor's device key is the same OTA_TOKEN in your firmware. BLE sample UUIDs and BLE update activation remain unchanged. Only one BLE client is supported, as before.

## Web ECG

The responsive monitor includes live plotting, raw/filtered display, five-second delayed zero-phase 0.5–40 Hz filtering, beat markers/BPM, pause/review, gain compensation, full-sine and positive-half-sine gain calibration, recording, CSV download, plot export and flatline tone. Filtering and beat analysis run in a worker; sample packets use compact binary transfer. Sequence gaps remain visible rather than being interpolated into invented samples. Keep the browser in the foreground while recording; mobile browsers may suspend background pages.

The desktop voltage axis now disables automatic SI prefixes. Values are explicitly in **mV**: 1 µV appears as 0.001 mV, not an incorrect `mmV` label.

## Firmware updates

- **Browser:** open the monitor, enter the device key, and use its firmware upload controls to select the built `.pio/build/esp32dev/firmware.bin`. The browser arms updating over Wi-Fi and uploads directly; Bluetooth is unnecessary. Works on the router network or hotspot.
- **Desktop OTA GUI:** enter the device IP or `http://ecg.local` in its Wi-Fi host field for Wi-Fi-only activation and upload. Leave the field empty to retain BLE activation followed by ArduinoOTA.
- **Command line:** `python ota_update.py --host 192.168.4.1` builds and uploads over the hotspot. Substitute the router-assigned IP when connected to a router. Existing BLE-triggered command-line use remains available.

Upload a standard ESP32-S3 application firmware.bin, not a merged flash image. Browser/HTTP uploads check chip ID and size before flashing; the Arduino update library verifies the completed image. Acquisition pauses during flashing. Successful updates reboot; an unused update window expires after five minutes without rebooting the ECG. Keep the existing token if you want existing clients to continue connecting.

The web service uses local HTTP and a device key, not TLS. Use a trusted local network and do not port-forward it to the Internet. Wi-Fi remains on as requested, including during BLE streaming; assess analog noise on your actual hardware.

## Recording metadata

Desktop and browser CSVs start with `# ecg_metadata={...}` containing the analog gain, compensation-enabled state, calibration method and available calibration parameters, ADC scale, display-filter selection, source and timestamp. Calibration controls are locked during recording so a single header accurately describes the recording.

**The voltage column remains raw ADC differential volts.** Gain and display filtering are not baked into that column. To obtain input volts, divide ADC volts by the recorded analog gain; multiply by 1000 for input mV. The header explicitly records this convention to prevent accidental double compensation. Older recordings without headers still load. External CSV tools should skip comment lines, e.g. `pandas.read_csv(path, comment='#')`.

## Validation and limits

Automated checks cover JavaScript signal processing, positive-half calibration, binary packet decoding, gaps/timestamp wrap/reboots, five-second filter delay, synthetic beat detection, recording metadata and legacy CSV compatibility. Python modules pass syntax compilation. Tests are in `tests/`.

Firmware compilation could not complete in the development environment because Arduino framework download failed certificate verification. No compiled firmware or EXE is included. Real-device Wi-Fi/BLE coexistence, captive popup behavior, browser rendering and OTA completion still require hardware validation. Build locally before flashing and retain your previous firmware for rollback.
