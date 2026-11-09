# BLE-triggered Wi-Fi OTA for the standard ESP32

Copy these files into your existing project, keeping the src/ paths. The Python
GUI and its requirements do not change. BLE is used to enter update mode;
the firmware itself is transferred over your existing Wi-Fi network.

## First installation (USB required once)

1. Edit src/ota_config.h: set the SSID/password of your 2.4 GHz Wi-Fi network.
   Keep the generated 16-character token, or replace it with your own 16-character
   alphanumeric token. Keep this file private. Escape quotes/backslashes in C++
   string literals if present in your Wi-Fi password.
2. Check the hardware settings at the top of src/main.cpp. This build targets
   ESP32-WROOM/esp32dev, 4 MB flash: SDA21, SCL22, RDY27. The supplied source
   selects ADS1115 A0-GND. If your working board uses A3, change
   ADS1X15_REG_CONFIG_MUX_SINGLE_0 to ADS1X15_REG_CONFIG_MUX_SINGLE_3.
   Preserve any other local pin, gain or channel changes from your working firmware.
3. From the project folder, upload over USB:

   ```powershell
   & "C:\pio\penv\Scripts\platformio.exe" run -e esp32dev --target upload
   ```

The partition table changes to min_spiffs.csv (two 0x1E0000-byte OTA slots).
This requires the USB upload of the partition table. Do not try the first
installation with OTA. Existing filesystem data is not preserved by a layout
change; this ECG project does not use a filesystem. Later OTA uploads update
only the application, not the partition table or bootloader.

## Later updates

Disconnect the ECG GUI from BLE (the firmware permits one BLE client), save
any active recording, and run from the project folder:

```powershell
& "C:\Users\tormo\AppData\Local\Programs\Python\Python312\python.exe" ota_update.py
```

The script builds esp32dev first, validates the image header/size, discovers the
ECG device, sends the authorized BLE command, reconnects after reboot, reads the
Wi-Fi IP over BLE, and invokes the installed Espressif espota.py uploader.
The existing bleak dependency is sufficient; all other script imports are
Python standard library modules.

Use --address AA:BB:CC:DD:EE:FF if multiple ECG devices are nearby. Optional:
--firmware PATH_TO_FIRMWARE_BIN skips building; --pio PATH selects PlatformIO;
--espota PATH selects Espressif's uploader if autodetection fails. Do not supply
a merged/full-flash binary. If changing the token in a new build, use --token
OLD_TOKEN for that upload: authorization uses the token in the running firmware.

Your PC must reach the ESP32 on the local network. Guest/client isolation can
block this. Allow the Python uploader through Windows Firewall on your private
network; espota uses UDP port 3232 on the ESP32 and a reverse TCP connection to
the PC. This does not require disconnecting the PC from its normal Wi-Fi.

## Runtime behavior

- Normal boot: only BLE/serial acquisition; Wi-Fi is never started.
- Authorized BLE write to c47e1003-17c4-4b56-9be5-125cece00001 sets a one-shot
  NVS flag, then restarts into update mode. No sampling/sender tasks are started
  in update mode; BLE remains available for status/IP discovery.
- Wi-Fi failure after 45 seconds, idle update mode after five minutes, or an OTA
  error returns to normal mode via restart. The one-shot flag is cleared early
  during boot, so resets do not keep the device stuck in update mode.
- Successful upload reboots into the uploaded firmware. Keep this OTA code in
  subsequent firmware if you want future wireless updates.
- Failed/incomplete uploads normally leave the running application selected.
  Automatic rollback after a successfully uploaded but faulty application is
  NOT implemented. USB recovery can still be necessary.
- ArduinoOTA.handle() performs transfer synchronously. Its transfer timeout
  handles a stalled transfer; the loop's extra deadline is not a watchdog for
  a CPU/stack hang.

## Authentication and validation

The BLE command requires the 16-character token; ArduinoOTA uses the same token
for upload authentication. This is intended for your trusted bench/LAN: BLE
command transport is not encrypted, and ArduinoOTA is not HTTPS or signed-firmware
verification. Do not expose it to the internet.

Checked here: Python syntax/help, image/size rejection, token parsing and a mocked
BLE mode-entry/reconnection/IP flow. Firmware has NOT been compiled in this
runtime or tested on an ESP32. Physical Wi-Fi/OTA operation remains unverified.
