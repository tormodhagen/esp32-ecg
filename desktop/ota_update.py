"""Build, enter Wi-Fi OTA via BLE, then upload using Espressif's espota.py.
Close the ECG GUI connection first. Run --help for options.
"""
import argparse
import asyncio
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import runpy
import contextlib

SERVICE = 'c47e1000-17c4-4b56-9be5-125cece00001'
COMMAND = 'c47e1003-17c4-4b56-9be5-125cece00001'
STATUS = 'c47e1002-17c4-4b56-9be5-125cece00001'


def config_token(project):
    text = (project / 'src/ota_config.h').read_text(encoding='utf-8')
    match = re.search(r'OTA_TOKEN\[\]\s*=\s*"([A-Za-z0-9]{16})"', text)
    if not match:
        raise ValueError('Use a 16-character alphanumeric OTA_TOKEN in src/ota_config.h')
    return match.group(1)


def find_pio(explicit):
    if explicit:
        return explicit
    for candidate in [shutil.which('pio'), shutil.which('platformio'),
                      r'C:\pio\penv\Scripts\platformio.exe',
                      str(Path.home()/'.platformio/penv/Scripts/platformio.exe'),
                      str(Path.home()/'.platformio/penv/bin/platformio')]:
        if candidate and Path(candidate).is_file():
            return candidate
    raise ValueError('PlatformIO not found. Pass --pio PATH_TO_PLATFORMIO')


def find_espota(explicit):
    if explicit:
        path = Path(explicit)
        if path.is_file(): return path
        raise ValueError(f'espota.py not found: {path}')
    bundled = Path(__file__).resolve().parent/'vendor/espota.py'
    if bundled.is_file(): return bundled
    roots = [Path(os.environ.get('PLATFORMIO_CORE_DIR', str(Path.home()/'.platformio'))),
             Path('C:/pio')]
    for root in roots:
        package = root/'packages/framework-arduinoespressif32'
        if package.is_dir():
            matches = sorted(package.rglob('espota.py'))
            if matches: return matches[0]
    raise ValueError('Pass --espota PATH to framework-arduinoespressif32/tools/espota.py')


def check_image(path):
    data = path.read_bytes()
    # XIAO ESP32-S3 application image (chip ID 9). Reject merged/full-flash and other chip targets.
    if len(data) < 24 or data[0] != 0xE9 or int.from_bytes(data[12:14], 'little') != 9:
        raise ValueError('Expected an ESP32-S3 application firmware.bin (not C6, classic ESP32 or merged flash)')
    if len(data) > 0x1E0000:
        raise ValueError('Image exceeds the min_spiffs.csv OTA slot (0x1E0000 bytes)')


async def enter_update_mode(address, token):
    from bleak import BleakClient, BleakScanner
    print('Searching for ESP32-ECG. Disconnect the live GUI first.')
    found = await BleakScanner.discover(timeout=6, return_adv=True)
    devices = [dev for dev, adv in found.values()
               if SERVICE in [u.lower() for u in adv.service_uuids]
               and (not address or dev.address.lower() == address.lower())]
    if len(devices) != 1:
        raise RuntimeError('Expected one ECG device. Use --address ADDRESS. Found: ' +
                           ', '.join(d.address for d in devices))
    device = devices[0]
    async with BleakClient(device, timeout=12) as client:
        if not client.services.get_characteristic(COMMAND):
            raise RuntimeError('OTA firmware is not installed. Perform the initial USB flash.')
        status = bytes(await client.read_gatt_char(STATUS)).decode(errors='replace').strip()
        if not status.startswith(('OTA_READY ', 'OTA_ACCEPTED', 'OTA_WAIT_WIFI', 'OTA_UPLOADING')):
            await client.write_gatt_char(COMMAND, token.encode('ascii'), response=True)
            # Allow the firmware to acknowledge before its scheduled reboot.
            try:
                status = bytes(await client.read_gatt_char(STATUS)).decode(errors='replace').strip()
            except Exception:
                status = ''  # It may already be rebooting; reconnect below.
        if status in ('OTA_CONFIG_REQUIRED', 'OTA_NVS_ERROR'):
            raise RuntimeError(status + ': check configuration and flash through USB')
        if status.startswith('OTA_READY '):
            return status.split()[1]
    print('Waiting for update mode and Wi-Fi (up to 70 seconds) …')
    deadline = time.monotonic()+70
    last_error = ''
    while time.monotonic() < deadline:
        await asyncio.sleep(2)
        try:
            async with BleakClient(device, timeout=6) as client:
                while client.is_connected and time.monotonic() < deadline:
                    status = bytes(await client.read_gatt_char(STATUS)).decode(errors='replace').strip()
                    if status.startswith('OTA_READY '):
                        return status.split()[1]
                    if not status.startswith('OTA_'):
                        raise RuntimeError('Board returned to ECG mode or rejected the token. Check Wi-Fi/token.')
                    await asyncio.sleep(1)
        except Exception as exc:
            last_error = str(exc)
    raise RuntimeError('OTA mode not ready. Check 2.4 GHz SSID/password and token. ' + last_error)


def http_endpoint(host):
    import urllib.parse
    parsed = urllib.parse.urlsplit(host.strip() if '://' in host else 'http://' + host.strip())
    if parsed.scheme != 'http' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a local device HTTP address, e.g. http://ecg.local')
    return urllib.parse.urlunsplit(('http', parsed.netloc, '', '', '')), parsed.hostname


def http_request(opener, request, timeout):
    import urllib.error
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode('utf-8', errors='replace').strip()
        token = request.get_header('X-ecg-key', '')
        if token: detail = detail.replace(token, '[REDACTED]')
        raise RuntimeError(f'{request.selector}: HTTP {exc.code} {exc.reason}: {detail or "empty device response"}') from None


def arm_http(host, token):
    import urllib.request
    base, hostname = http_endpoint(host)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(base+'/ota/arm', data=b'arm=1', headers={
        'X-ECG-Key': token, 'Content-Type':'application/x-www-form-urlencoded'}, method='POST')
    http_request(opener, request, 15)
    return hostname


def upload_http(host, token, image):
    """Optional direct HTTP upload, with the device's full rejection reason."""
    import urllib.request
    import uuid
    base, _ = http_endpoint(host)
    arm_http(host, token)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    boundary = 'ECG' + uuid.uuid4().hex
    data = image.read_bytes()
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="firmware"; filename="firmware.bin"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode() + data + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(base+'/ota/upload', data=body, headers={
        'X-ECG-Key':token, 'X-Image-Size':str(len(data)),
        'Content-Type':'multipart/form-data; boundary='+boundary}, method='POST')
    print('Uploading over Wi-Fi. Keep power connected.', flush=True)
    print(http_request(opener, req, 180).decode('utf-8', errors='replace'), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=(Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]/'firmware'))
    parser.add_argument('--environment', default='esp32dev', help='PlatformIO environment name (default: esp32dev)')
    parser.add_argument('--http-upload', action='store_true', help='Use direct multipart HTTP transfer instead of ArduinoOTA')
    parser.add_argument('--host', help='Wi-Fi-only OTA: IP or http://ecg.local (no Bluetooth required)')
    parser.add_argument('--address', help='BLE address if multiple ECG devices are nearby')
    parser.add_argument('--pio', help='PlatformIO executable path')
    parser.add_argument('--espota', help='Explicit Espressif espota.py path')
    parser.add_argument('--firmware', type=Path, help='Upload this firmware.bin instead of building')
    parser.add_argument('--token', help='Token in the RUNNING firmware; defaults to ota_config.h')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.environment):
        raise ValueError('Invalid PlatformIO environment name')
    project = args.project.resolve()
    print('Target: Seeed Studio XIAO ESP32-S3 · chip ID 9 · OTA slot 1,966,080 bytes')
    token = args.token or os.environ.get('ECG_OTA_TOKEN') or config_token(project)
    if not re.fullmatch(r'[A-Za-z0-9]{16}', token):
        raise ValueError('Token must be 16 ASCII letters/digits')
    image = args.firmware
    if image is None:
        subprocess.run([find_pio(args.pio), 'run', '-e', args.environment], cwd=project, check=True)
        image = project/'.pio/build'/args.environment/'firmware.bin'
    image = image.resolve()
    check_image(image)
    if args.host and args.http_upload:
        upload_http(args.host, token, image)
        print('Upload reported successful. Reconnect to verify firmware.')
        return
    espota = find_espota(args.espota)  # Validate local tools BEFORE interrupting ECG.
    if args.host:
        ip = arm_http(args.host, token)
        print('OTA activated over Wi-Fi; transferring with ArduinoOTA (no Bluetooth).')
    else:
        ip = asyncio.run(enter_update_mode(args.address, token))
    print(f'Uploading to {ip}. Allow Python through the private-network firewall if prompted.')
    # Execute the official uploader inside this worker, also when frozen.
    # A packaged sys.executable is NOT a Python interpreter.
    argv = sys.argv
    sys.argv = [str(espota), '-i', ip, '-p', '3232', '-r', '-d',
                '-a', token, '-f', str(image)]
    class RedactedStream:
        def __init__(self, stream): self.stream = stream
        def write(self, value):
            return self.stream.write(value.replace(token, '[REDACTED]'))
        def flush(self): self.stream.flush()
        def isatty(self): return False
    code = 0
    try:
        with contextlib.redirect_stdout(RedactedStream(sys.stdout)), contextlib.redirect_stderr(RedactedStream(sys.stderr)):
            try:
                runpy.run_path(str(espota), run_name='__main__')
            except SystemExit as exc:
                code = exc.code or 0
    finally:
        sys.argv = argv
    if code:
        raise RuntimeError('Transfer failed. See the log above. Device reboot has not been verified.')
    print('Upload reported successful. Reconnect ECG Monitor to verify the device.')


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(line_buffering=True)
    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelled. The ESP32 will time out back to ECG mode.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
