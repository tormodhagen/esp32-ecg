import argparse
import asyncio
import csv
import json
from datetime import datetime, timezone
from recording_metadata import snapshot, write_header, read_header
import sys
import time
import tempfile
import wave
from collections import deque
from pathlib import Path
import numpy as np
import serial
from serial.tools import list_ports
from PySide6 import QtCore, QtWidgets, QtMultimedia, QtGui
import pyqtgraph as pg
from ui_theme import apply_theme, heading
from ecg_signal import Decoder, analyze, display_filter
from ecg_calibration import estimate_gain
from ecg_ble import SERVICE_UUID, DATA_UUID, decode_packet


def is_flat_signal(t, v, threshold_v=.005):
    """Low amplitude for 3 s of continuous raw ADC data, not a medical diagnosis."""
    t, v = np.asarray(t), np.asarray(v)
    if len(t) < 100 or not np.all(np.isfinite(t)) or not np.all(np.isfinite(v)):
        return False
    m = t >= t[-1] - 3.0
    t, v = t[m], v[m]
    if len(t) < 100 or t[-1]-t[0] < 2.98:
        return False
    dt = np.diff(t)
    if np.any(dt <= 0) or np.max(dt) > .020:
        return False
    return bool(np.percentile(v, 99)-np.percentile(v, 1) < threshold_v)


class FlatlineTone(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.directory = tempfile.TemporaryDirectory(prefix='ecg-tone-')
        path = Path(self.directory.name) / 'flatline.wav'
        rate = 44100
        samples = (np.sin(2*np.pi*700*np.arange(rate)/rate)*.35*32767).astype('<i2')
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
            wav.writeframes(samples.tobytes())
        self.effect = QtMultimedia.QSoundEffect(self)
        self.effect.setSource(QtCore.QUrl.fromLocalFile(str(path)))
        self.effect.setLoopCount(QtMultimedia.QSoundEffect.Loop.Infinite.value)
        self.effect.setVolume(.15)
        self.requested = False
        self.effect.statusChanged.connect(self.sync)

    def set_active(self, active):
        self.requested = bool(active)
        self.sync()

    def sync(self):
        if not self.requested:
            self.effect.stop()
        elif self.effect.status() == QtMultimedia.QSoundEffect.Ready and not self.effect.isPlaying():
            self.effect.play()

    def close(self):
        self.set_active(False)
        self.effect.setSource(QtCore.QUrl())
        self.directory.cleanup()


def open_ecg_serial(port, reset=True):
    # Set line states BEFORE open. PySerial defaults assert both lines;
    # a USB-UART bridge may wire these to ESP32 EN and BOOT.
    ser = serial.Serial(port=None, baudrate=460800, timeout=.1,
                        rtscts=False, dsrdtr=False, xonxoff=False)
    ser.dtr = False
    ser.rts = False
    ser.port = port
    ser.open()
    try:
        if reset:
            # EN reset: DTR remains deasserted so BOOT is not selected.
            ser.rts = True
            time.sleep(.15)
            ser.rts = False
            time.sleep(1.5)
    except Exception:
        try:
            ser.rts = False
        finally:
            ser.close()
        raise
    return ser


class Reader(QtCore.QThread):
    batch = QtCore.Signal(object)
    message = QtCore.Signal(str)

    def __init__(self, port='', replay=None, ble=False, reset_port=None):
        super().__init__()
        self.port, self.replay, self.ble = port, replay, ble
        self.reset_port = reset_port

    async def run_ble(self):
        from bleak import BleakScanner, BleakClient
        if self.reset_port:
            self.message.emit(f'RTS reset via {self.reset_port} …')
            with open_ecg_serial(self.reset_port):
                pass
        self.message.emit('Searching for ESP32-ECG …')
        # Run discovery in the worker asyncio loop, not the Qt GUI thread.
        found = await BleakScanner.discover(timeout=5, return_adv=True)
        devices = [device for device, adv in found.values()
                   if SERVICE_UUID in [u.lower() for u in adv.service_uuids]
                   and (not self.port or device.address.lower() == self.port.lower())]
        if self.isInterruptionRequested():
            return
        if not devices:
            raise RuntimeError('No ECG device found. Check power and Bluetooth.')
        if len(devices) != 1:
            raise RuntimeError('Multiple ECG devices found. Enter an address: ' +
                               ', '.join(d.address for d in devices))
        decoder = Decoder()
        pending = []
        disconnected = asyncio.Event()
        def notification(_, data):
            try:
                pending.extend(decode_packet(data, decoder))
            except ValueError as exc:
                self.message.emit(str(exc))
        async with BleakClient(devices[0], timeout=10,
                               disconnected_callback=lambda _: disconnected.set()) as client:
            if self.isInterruptionRequested():
                return
            await client.start_notify(DATA_UUID, notification)
            self.message.emit(f'BLE connected: {devices[0].address} · MTU {client.mtu_size}')
            last_packet = time.monotonic()
            last_status = 0.
            status_uuid = 'c47e1002-17c4-4b56-9be5-125cece00001'
            has_status = client.services.get_characteristic(status_uuid) is not None
            while not self.isInterruptionRequested() and not disconnected.is_set():
                await asyncio.sleep(.02)
                if pending:
                    self.batch.emit(pending[:])
                    pending.clear()
                    last_packet = time.monotonic()
                if time.monotonic()-last_packet > 2 and time.monotonic()-last_status > 2:
                    last_status = time.monotonic()
                    if has_status and client.is_connected:
                        data = await asyncio.wait_for(client.read_gatt_char(status_uuid), timeout=3)
                        self.message.emit('BLE connected, no samples: ' + data.decode('utf-8', errors='replace').strip())
                    else:
                        self.message.emit('BLE connected, no samples — check ADS1115/ALERT and firmware')
            if pending:
                self.batch.emit(pending[:])
            if disconnected.is_set():
                self.message.emit('BLE disconnected. Select Connect to retry.')

    def run(self):
        try:
            if self.ble and not self.replay:
                asyncio.run(self.run_ble())
                return
            if self.replay:
                # WaveForms export; also accepts CSV recorded by this application.
                with open(self.replay, encoding='utf-8-sig') as f:
                    rows = csv.DictReader(line for line in f if line.strip() and not line.startswith('#'))
                    data = []
                    for r in rows:
                        if 'Time (s)' in r:
                            data.append((float(r['Time (s)']), float(r['Channel 1 (V)'])))
                        else:
                            data.append((float(r['time_s']), float(r['voltage_V'])))
                a = np.asarray(data)
                if a.ndim != 2 or len(a) < 2 or np.any(np.diff(a[:, 0]) <= 0):
                    raise ValueError('Replay requires increasing timestamps and at least two samples')
                a[:, 0] -= a[0, 0]
                start, i = time.monotonic(), 0
                while i < len(a) and not self.isInterruptionRequested():
                    end = np.searchsorted(a[:, 0], time.monotonic()-start, side='right')
                    if end > i:
                        self.batch.emit([(float(t), float(v), k, int(t*1e6), round(v/.000125), 0, False)
                                         for k, (t, v) in enumerate(a[i:end], i)])
                        i = end
                    self.msleep(20)
                self.message.emit('Replay ferdig')
                return
            decoder = Decoder()
            with open_ecg_serial(self.port) as ser:
                ser.reset_input_buffer()
                pending, last = [], time.monotonic()
                buffer = bytearray()
                while not self.isInterruptionRequested():
                    buffer.extend(ser.read(ser.in_waiting or 1))
                    while b'\n' in buffer:
                        line, _, buffer = buffer.partition(b'\n')
                        text = line.decode('ascii', errors='replace')
                        if text.startswith('#'):
                            self.message.emit(text)
                            continue
                        try:
                            row = decoder.feed(text)
                            if row: pending.append(row)
                        except ValueError:
                            self.message.emit('Invalid packet discarded')
                    if len(buffer) > 4096:
                        buffer.clear()
                        self.message.emit('Invalid serial stream')
                    if pending and time.monotonic()-last >= .04:
                        self.batch.emit(pending)
                        pending, last = [], time.monotonic()
                if pending: self.batch.emit(pending)
        except Exception as exc:
            self.message.emit(f'Error: {exc}')


class Window(QtWidgets.QMainWindow):
    def __init__(self, replay=None, reset_port=None):
        super().__init__()
        self.setWindowTitle('ECG Monitor')
        self.resize(1200, 800)
        self.setMinimumSize(720, 480)
        self.updater = None
        update_action = self.menuBar().addMenu('Device').addAction('Firmware update…')
        update_action.triggered.connect(self.open_updater)
        self.settings = QtCore.QSettings('ECG Tools', 'Monitor')
        self.paused = False
        self.record_metadata = {}
        try:
            self.calibration_metadata = json.loads(str(self.settings.value("calibration_metadata", '{"method":"manual_or_unknown"}')))
        except (ValueError, TypeError):
            self.calibration_metadata = {"method": "manual_or_unknown"}
        self.record_wall_start = None
        self.data = deque(maxlen=40000)
        self.worker = None
        self.recording = False
        self.recorded_rows = []
        self.record_start = None
        self.lost = 0
        self.last_received = 0
        self.last_analysis = 0
        self.beats = np.array([])
        self.replay = replay
        self.reset_port = reset_port
        self.flat_active = False
        self.tone = FlatlineTone(self)
        self.sound_test_timer = QtCore.QTimer(self)
        self.sound_test_timer.setSingleShot(True)
        self.sound_test_timer.timeout.connect(self.update_tone)
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        self.setCentralWidget(scroll)
        main = QtWidgets.QWidget(); scroll.setWidget(main)
        layout = QtWidgets.QVBoxLayout(main)
        layout.setContentsMargins(24, 20, 24, 16); layout.setSpacing(12)
        layout.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
        heading(layout, 'ECG Monitor', 'Live acquisition · ADS1115 / ESP32')
        connection = QtWidgets.QGroupBox('Connection')
        layout.addWidget(connection)
        bar = QtWidgets.QHBoxLayout(connection)
        self.transport = QtWidgets.QComboBox()
        self.transport.addItems(['USB / serial', 'Bluetooth LE'])
        self.transport.setEnabled(not replay)
        bar.addWidget(self.transport)
        self.ports = QtWidgets.QComboBox(); bar.addWidget(self.ports)
        self.transport.currentIndexChanged.connect(self.refresh)
        refresh = QtWidgets.QPushButton('Refresh'); refresh.clicked.connect(self.refresh); bar.addWidget(refresh)
        self.connect_button = QtWidgets.QPushButton('Play recording' if replay else 'Connect')
        self.connect_button.setObjectName('primary')
        self.connect_button.clicked.connect(self.toggle); bar.addWidget(self.connect_button)
        self.ports.setMinimumWidth(220)
        bar.setStretchFactor(self.ports, 1)
        replay_button = QtWidgets.QPushButton('Open recording…')
        replay_button.clicked.connect(self.open_replay); bar.addWidget(replay_button)
        controls = QtWidgets.QHBoxLayout(); layout.addLayout(controls)
        self.mode = QtWidgets.QComboBox(); self.mode.addItems(['Raw signal (V)', 'Filtered · 0.5–40 Hz (V) · 5 s delay']); controls.addWidget(self.mode)
        self.span = QtWidgets.QSpinBox(); self.span.setRange(3, 20); self.span.setValue(8); self.span.setSuffix(' s'); controls.addWidget(self.span); controls.addStretch()
        self.record_button = QtWidgets.QPushButton('Start recording'); self.record_button.clicked.connect(self.record); controls.addWidget(self.record_button)
        audio_toggle = QtWidgets.QPushButton('Audio settings'); audio_toggle.setCheckable(True); controls.addWidget(audio_toggle)
        sound_box = QtWidgets.QGroupBox('Low-signal audio'); layout.addWidget(sound_box)
        sound_box.setVisible(False); audio_toggle.toggled.connect(sound_box.setVisible)
        sound_bar = QtWidgets.QHBoxLayout(sound_box)
        self.sound_enabled = QtWidgets.QCheckBox('Enable tone'); self.sound_enabled.setChecked(True)
        self.sound_enabled.toggled.connect(self.update_tone); sound_bar.addWidget(self.sound_enabled)
        sound_bar.addWidget(QtWidgets.QLabel('ADC threshold:'))
        self.flat_threshold = QtWidgets.QDoubleSpinBox(); self.flat_threshold.setRange(.5, 100)
        self.flat_threshold.setValue(5); self.flat_threshold.setSuffix(' mV'); sound_bar.addWidget(self.flat_threshold)
        sound_bar.addWidget(QtWidgets.QLabel('Volume:'))
        self.volume = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.volume.setRange(0, 100); self.volume.setValue(15)
        self.volume.setMaximumWidth(140); self.volume.valueChanged.connect(lambda x: self.tone.effect.setVolume(x/100))
        sound_bar.addWidget(self.volume)
        test_sound = QtWidgets.QPushButton('Test tone'); test_sound.clicked.connect(self.test_tone); sound_bar.addWidget(test_sound)
        sound_bar.addStretch()
        self.flat_status = QtWidgets.QLabel('Waiting for data'); layout.addWidget(self.flat_status)
        self.bpm = QtWidgets.QLabel('— BPM'); self.bpm.setStyleSheet('font-size: 38px; font-weight: 600; color: #185c91;'); layout.addWidget(self.bpm)
        self.quality = QtWidgets.QLabel('Experimental BPM estimate · not a diagnostic reading'); layout.addWidget(self.quality)
        self.plot = pg.PlotWidget(); self.plot.setBackground('#ffffff'); self.plot.showGrid(x=True, y=True, alpha=.2)
        self.plot.getAxis('left').setTextPen('#607083'); self.plot.getAxis('bottom').setTextPen('#607083')
        self.plot.setLabel('bottom', 'Time', units='s'); self.plot.setLabel('left', 'Voltage', units='V'); layout.addWidget(self.plot, 1)
        self.curve = self.plot.plot(pen=pg.mkPen('#185c91', width=1.6), connect='finite')
        self.markers = self.plot.plot(pen=None, symbol='o', symbolSize=6, symbolBrush='#be7925')
        self.stats = QtWidgets.QLabel(); layout.addWidget(self.stats)
        self.status = QtWidgets.QLabel('Ready · connect to begin acquisition'); self.status.setWordWrap(True); layout.addWidget(self.status)
        inspect = QtWidgets.QHBoxLayout(); layout.insertLayout(layout.indexOf(self.plot), inspect)
        self.pause_button = QtWidgets.QPushButton('Pause view · Space'); self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self.pause_view); inspect.addWidget(self.pause_button)
        reset_view = QtWidgets.QPushButton('Fit amplitude'); reset_view.clicked.connect(lambda: self.plot.enableAutoRange(axis='y')); inspect.addWidget(reset_view)
        export = QtWidgets.QPushButton('Export plot…'); export.clicked.connect(self.export_plot); inspect.addWidget(export)
        self.record_status = QtWidgets.QLabel('Not recording'); inspect.addWidget(self.record_status); inspect.addStretch()
        discard = QtWidgets.QPushButton('Discard recording…'); discard.clicked.connect(self.discard_recording); inspect.addWidget(discard)
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.setToolTip('Pause to inspect. Drag to pan; use the wheel to zoom. Fit amplitude restores vertical scaling.')
        self.mode.setCurrentIndex(int(self.settings.value('mode', 0)))
        self.span.setValue(int(self.settings.value('span', 8)))
        self.volume.setValue(int(self.settings.value('volume', 15)))
        self.flat_threshold.setValue(float(self.settings.value('threshold', 5)))
        self.sound_enabled.setChecked(str(self.settings.value('sound', 'true')).lower() == 'true')
        gain_row = QtWidgets.QHBoxLayout(); layout.insertLayout(layout.indexOf(self.plot), gain_row)
        self.input_units = QtWidgets.QCheckBox('Input voltage · mV')
        self.input_units.setToolTip('Differential ADC voltage divided by total analog gain. Old single-ended recordings retain their DC offset.')
        gain_row.addWidget(self.input_units)
        gain_row.addWidget(QtWidgets.QLabel('Analog gain (V/V)'))
        self.analog_gain = QtWidgets.QDoubleSpinBox(); self.analog_gain.setRange(.001, 1000000)
        self.analog_gain.setDecimals(3); self.analog_gain.setValue(float(self.settings.value('analog_gain', 1.0)))
        self.analog_gain.setToolTip('Enter the actual total analog gain or calibrate with a known sine wave. Default 1 is not a calibration.')
        gain_row.addWidget(self.analog_gain)
        calibrate = QtWidgets.QPushButton('Calibrate gain…'); calibrate.clicked.connect(self.calibrate_gain); gain_row.addWidget(calibrate)
        gain_row.addStretch()
        self.plot.getAxis("left").enableAutoSIPrefix(False)
        self.analog_gain.valueChanged.connect(self.manual_gain_changed)
        if replay:
            try:
                meta = read_header(replay)
                if meta:
                    self.analog_gain.setValue(float(meta["analog_gain_v_per_v"]))
                    self.input_units.setChecked(bool(meta.get("gain_compensation_enabled", False)))
                    self.calibration_metadata = meta.get("calibration", {"method": "unknown"})
            except (OSError, ValueError, KeyError) as exc:
                self.status.setText(f"Recording metadata could not be read: {exc}")
        self.input_units.toggled.connect(self.change_voltage_units)
        self.analog_gain.valueChanged.connect(self.change_voltage_units)
        self.shortcuts = []
        for key, action in [('Space', self.pause_button.click), ('Ctrl+R', self.record), ('Ctrl+E', self.export_plot)]:
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self); shortcut.activated.connect(action); self.shortcuts.append(shortcut)
        self.timer = QtCore.QTimer(self); self.timer.timeout.connect(self.draw); self.timer.start(40)
        self.refresh()
        if replay: self.status.setText(f'Recording: {Path(replay).name}')

    def pause_view(self, paused):
        self.paused = paused
        self.pause_button.setText('Resume view · Space' if paused else 'Pause view · Space')
        if paused:
            self.plot.setTitle('Paused view · acquisition and recording continue', color='#607083', size='10pt')
        else:
            self.plot.enableAutoRange(axis='y')
            self.draw()

    def manual_gain_changed(self, *_):
        self.calibration_metadata = {"method": "manual", "gain_v_per_v": self.analog_gain.value()}

    def change_voltage_units(self, *_):
        if self.paused: self.pause_button.setChecked(False)
        self.plot.enableAutoRange(axis='y')
        self.draw()

    def calibrate_gain(self):
        if self.recording:
            QtWidgets.QMessageBox.information(self, 'Calibration', 'Stop the recording before changing calibration.'); return
        dialog = QtWidgets.QDialog(self); dialog.setWindowTitle('Calibrate analog gain')
        form = QtWidgets.QFormLayout(dialog)
        note = QtWidgets.QLabel('''Inject a known sine wave at the analog frontend input.
DC-offset sine is supported. Let the circuit settle, then collect at least 5 cycles.
The estimate uses up to 20 seconds of raw ADC data.'''); form.addRow(note)
        freq = QtWidgets.QDoubleSpinBox(); freq.setRange(.5, 40); freq.setDecimals(3); freq.setValue(1); freq.setSuffix(' Hz')
        amp = QtWidgets.QDoubleSpinBox(); amp.setRange(.001, 1000); amp.setDecimals(3); amp.setValue(10); amp.setSuffix(' mV pp')
        form.addRow('Sine frequency', freq); form.addRow('Input peak-to-peak', amp)
        positive = QtWidgets.QCheckBox('Fit positive half only')
        positive.setToolTip('Use only an undistorted positive lobe. DC offset is fitted automatically in both modes. Amplitude still means the full sine peak-to-peak value.')
        form.addRow('Fit region', positive)
        form.addRow(QtWidgets.QLabel('''Example: 5 mV peak = 10 mV peak-to-peak in BOTH modes.
Positive-half mode requires an undistorted positive lobe.
Prefer an offset sine that keeps the whole circuit linear.
Gain is measured at this frequency, including analog filtering.'''))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        if dialog.exec() != QtWidgets.QDialog.Accepted: return
        if len(self.data) < 100 or time.monotonic()-self.last_received > 1:
            QtWidgets.QMessageBox.warning(self, 'Calibration', 'Collect a fresh calibration signal first.'); return
        a = np.asarray(self.data); m = a[:,0] >= a[-1,0]-20
        try:
            gain, pp, residual = estimate_gain(a[m,0], a[m,1], freq.value(), amp.value(), positive_half=positive.isChecked())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, 'Calibration rejected', str(exc)); return
        answer = QtWidgets.QMessageBox.question(self, 'Apply calibration?',
            f'Measured gain: {gain:.3f} V/V\nReconstructed full ADC sine: {pp*1000:.3f} mV pp\nResidual: {residual*100:.1f}% of fitted sine RMS\n\nApply this gain?')
        if answer == QtWidgets.QMessageBox.Yes:
            self.analog_gain.setValue(gain); self.settings.setValue('analog_gain', gain)
            self.calibration_metadata = dict(method='positive_half_sine' if positive.isChecked() else 'full_sine',
                frequency_hz=freq.value(), input_mV_pp=amp.value(), fitted_adc_V_pp=pp,
                residual_fraction=residual, gain_v_per_v=gain, calibrated_utc=datetime.now(timezone.utc).isoformat())
            self.settings.setValue('calibration_metadata', json.dumps(self.calibration_metadata))
            self.status.setText(f'Gain calibrated at {freq.value():g} Hz: {gain:.3f} V/V')

    def export_plot(self):
        import pyqtgraph.exporters
        folder = str(self.settings.value('save_folder', str(Path.home())))
        name, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export visible plot', str(Path(folder)/'ecg-plot.png'), 'PNG image (*.png)')
        if not name: return
        if not Path(name).suffix: name += '.png'
        try:
            exporter = pyqtgraph.exporters.ImageExporter(self.plot.plotItem)
            exporter.parameters()['width'] = 2000
            exporter.export(name)
            self.settings.setValue('calibration_metadata', json.dumps(self.calibration_metadata))
            self.settings.setValue('save_folder', str(Path(name).parent))
            self.status.setText(f'Plot exported to {name}')
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, 'Export failed', str(exc))

    def discard_recording(self):
        if not self.recorded_rows and not self.recording: return
        answer = QtWidgets.QMessageBox.question(self, 'Discard recording?', 'Discard all samples in this recording? This cannot be undone.',
                                               QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
        if answer != QtWidgets.QMessageBox.Yes: return
        self.recording = False; self.recorded_rows.clear(); self.record_start = None
        self.analog_gain.setEnabled(True); self.input_units.setEnabled(True)
        self.record_button.setText('Start recording'); self.record_status.setText('Not recording')
        self.status.setText('Recording discarded')

    def open_updater(self):
        if self.updater is None:
            from ota_gui import OtaWindow
            self.updater = OtaWindow(self)
        self.updater.show(); self.updater.raise_(); self.updater.activateWindow()

    def prepare_update(self):
        if self.recording or self.recorded_rows:
            QtWidgets.QMessageBox.information(self, 'Save recording', 'Stop and save or discard your recording before updating.'); return False
        self.stop()
        return True

    def open_replay(self):
        if self.worker and self.worker.isRunning():
            QtWidgets.QMessageBox.information(self, 'Recording playback', 'Disconnect before opening a recording.')
            return
        name, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Open recording', '', 'CSV recordings (*.csv)')
        if name:
            child = Window(Path(name))
            if not hasattr(self, 'replay_windows'): self.replay_windows = []
            self.replay_windows.append(child)
            child.setAttribute(QtCore.Qt.WA_DeleteOnClose)
            child.destroyed.connect(lambda: self.replay_windows.remove(child))
            child.show()

    def update_tone(self, *_):
        self.tone.set_active(self.sound_enabled.isChecked() and
                             (self.flat_active or self.sound_test_timer.isActive()))

    def test_tone(self):
        self.sound_enabled.setChecked(True)
        self.sound_test_timer.start(1000)
        self.update_tone()

    def silence(self):
        self.flat_active = False
        self.sound_test_timer.stop()
        self.tone.set_active(False)
        self.flat_status.setText('No recent samples')

    def refresh(self):
        if self.transport.currentIndex() == 1:
            self.ports.clear(); self.ports.setEditable(True)
            self.ports.lineEdit().setPlaceholderText('Automatic discovery, or BLE address')
            return
        self.ports.setEditable(False)
        selected = self.ports.currentData(); self.ports.clear()
        for p in list_ports.comports(): self.ports.addItem(f'{p.device} — {p.description}', p.device)
        i = self.ports.findData(selected)
        if i >= 0: self.ports.setCurrentIndex(i)

    def toggle(self):
        if self.updater and self.updater.process and self.updater.process.state() != QtCore.QProcess.NotRunning:
            QtWidgets.QMessageBox.information(self, 'Update in progress', 'Wait for the firmware update before reconnecting.'); return
        if self.worker and self.worker.isRunning():
            self.stop(); return
        if not self.replay and self.transport.currentIndex() == 0 and not self.ports.currentData():
            self.status.setText('Select a serial port'); return
        # Each connection/replay gets a separate recording to preserve monotonic time.
        self.close_recording()
        if self.recorded_rows:
            self.status.setText('Save the pending recording before reconnecting')
            return
        self.pause_button.setChecked(False)
        self.data.clear(); self.lost = 0; self.beats = np.array([]); self.bpm.setText('— BPM')
        ble = self.transport.currentIndex() == 1
        port = self.ports.currentText().strip() if ble else self.ports.currentData()
        self.worker = Reader(port, self.replay, ble, self.reset_port)
        self.transport.setEnabled(False)
        self.worker.batch.connect(self.receive); self.worker.message.connect(self.status.setText)
        self.worker.finished.connect(self.finished)
        self.worker.start(); self.connect_button.setText('Disconnect'); self.status.setText('Waiting for data …')

    def finished(self):
        self.transport.setEnabled(not self.replay)
        self.silence()
        self.connect_button.setText('Play recording' if self.replay else 'Connect')
        self.close_recording()
        self.bpm.setText('— BPM')

    def stop(self):
        self.silence()
        if self.worker:
            self.worker.requestInterruption()
            # Keep the GUI responsive while BLE discovery/connect finishes.
            while not self.worker.wait(20):
                QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)
        self.close_recording()
        self.connect_button.setText('Play recording' if self.replay else 'Connect')

    def receive(self, rows):
        for t, v, seq, us, raw, lost, reset in rows:
            if reset:
                self.data.clear(); self.beats = np.array([]); self.bpm.setText('— BPM')
                self.silence()
                self.status.setText('ESP32 restarted')
            self.data.append((t, v)); self.lost += lost
            if self.recording:
                if self.record_start is None:
                    self.record_start = t
                self.recorded_rows.append([f'{t-self.record_start:.6f}', f'{v:.6f}', seq, us, raw, lost, int(reset)])
        self.last_received = time.monotonic()

    def record(self):
        if self.recording:
            self.close_recording()
            return
        if self.recorded_rows:
            self.save_recording()
            return
        if not self.worker or not self.worker.isRunning():
            self.status.setText('Connect before starting a recording')
            return
        self.record_start = None
        self.record_metadata = snapshot(self.analog_gain.value(), self.input_units.isChecked(),
            dict(self.calibration_metadata), "0.5-40Hz zero-phase; 5s display delay" if self.mode.currentIndex() == 1 else "raw",
            "replay" if self.replay else "live")
        self.analog_gain.setEnabled(False); self.input_units.setEnabled(False)
        self.recording = True
        self.record_wall_start = time.monotonic()
        self.record_button.setText('Stop and save')
        self.status.setText('Recording · select Stop and save when finished')

    def close_recording(self):
        if not self.recording:
            return
        # Freeze the buffer BEFORE opening a modal dialog; receive() may continue.
        self.recording = False
        self.analog_gain.setEnabled(True); self.input_units.setEnabled(True)
        if self.recorded_rows:
            self.record_button.setText('Save recording')
            self.save_recording()
        else:
            self.record_button.setText('Start recording')
            self.status.setText('No samples were recorded')

    def save_recording(self):
        if not self.recorded_rows:
            return
        name, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save recording', str(Path(str(self.settings.value('save_folder', str(Path.home()))))/'ekg.csv'), 'CSV (*.csv)')
        if not name:
            self.status.setText('Recording retained in memory — select Save recording to retry')
            return
        if not Path(name).suffix:
            name += '.csv'
        try:
            with open(name, 'w', newline='', encoding='utf-8') as f:
                write_header(f, self.record_metadata)
                writer = csv.writer(f)
                writer.writerow(['time_s','voltage_V','sequence','device_us','raw','lost_before','device_reset'])
                writer.writerows(self.recorded_rows)
        except OSError as exc:
            self.status.setText(f'Save failed; recording retained: {exc}')
            return
        self.settings.setValue('calibration_metadata', json.dumps(self.calibration_metadata))
        self.settings.setValue('save_folder', str(Path(name).parent))
        count = len(self.recorded_rows)
        self.recorded_rows.clear()
        self.record_start = None
        self.record_button.setText('Start recording')
        self.status.setText(f'Saved {count} samples to {name}')

    def draw(self):
        if self.recording:
            elapsed = int(time.monotonic()-self.record_wall_start)
            self.record_status.setText(f'Recording {elapsed//60:02d}:{elapsed%60:02d} · {len(self.recorded_rows):,} samples')
            self.record_status.setStyleSheet('color: #a83232; font-weight: 600;')
        else:
            self.record_status.setText(f'{len(self.recorded_rows):,} unsaved samples' if self.recorded_rows else 'Not recording')
            self.record_status.setStyleSheet('')
        if len(self.data) < 100:
            self.flat_active = False
            self.update_tone()
            return
        a = np.asarray(self.data); t, v = a[:, 0], a[:, 1]
        # Include five seconds of future data and additional left-edge context.
        m = t >= t[-1]-35; t, v = t[m], v[m]
        now = time.monotonic()
        stale = now-self.last_received > 1 or not self.worker or not self.worker.isRunning()
        self.flat_active = not stale and is_flat_signal(t, v, self.flat_threshold.value()/1000)
        self.update_tone()
        self.flat_status.setText('No recent samples' if stale else
                                ('Low amplitude ≥ 3 s' if self.flat_active else 'Signal amplitude above threshold'))
        self.flat_status.setStyleSheet('color: #d54848; font-weight: bold;' if self.flat_active else '')
        if self.tone.effect.status() == QtMultimedia.QSoundEffect.Error:
            self.flat_status.setText(self.flat_status.text() + ' · Audio unavailable')
        if stale:
            self.bpm.setText('— BPM'); self.quality.setText('No recent samples')
        elif now-self.last_analysis >= .25:
            recent = t >= t[-1]-12
            bpm, _, note = analyze(t[recent], v[recent])
            _, self.beats, _ = analyze(t, v)
            self.bpm.setText('— BPM' if bpm is None else f'{bpm:.0f} BPM')
            self.quality.setText(note); self.last_analysis = now
        if self.paused:
            return
        self.plot.setLabel('left', 'Input voltage' if self.input_units.isChecked() else 'ADC voltage', units='mV' if self.input_units.isChecked() else 'V')
        filtered = self.mode.currentIndex() == 1
        end = t[-1] - 5.0 if filtered else t[-1]
        y = v.copy()
        if filtered:
            # Filter each continuous segment with its newer samples included.
            # Never show raw data under the filtered label after a gap.
            y = np.full_like(v, np.nan)
            boundaries = np.r_[0, np.flatnonzero(np.diff(t) > .020) + 1, len(t)]
            for start, stop in zip(boundaries[:-1], boundaries[1:]):
                if stop-start < 100 or t[stop-1]-t[start] < 5.0:
                    continue
                segment = display_filter(t[start:stop], v[start:stop])
                segment[t[start:stop] > t[stop-1]-5.0] = np.nan
                y[start:stop] = segment
        visible = (t >= end-self.span.value()) & (t <= end)
        tx, yy = t[visible], y[visible].copy()
        if len(tx):
            yy[np.r_[False, np.diff(tx) > .020]] = np.nan
            scale = 1000/self.analog_gain.value() if self.input_units.isChecked() else 1.0
            self.curve.setData(tx, yy*scale)
            b = self.beats[(self.beats >= tx[0]) & (self.beats <= tx[-1])]
            by = np.interp(b, t, y)
            valid = np.isfinite(by)
            self.markers.setData(b[valid], by[valid]*scale)
        else:
            self.curve.setData([], []); self.markers.setData([], [])
        self.plot.setXRange(max(0, end-self.span.value()), max(self.span.value(), end), padding=0)
        self.plot.setTitle(('Filtered · 5 s display delay' if np.any(np.isfinite(yy)) else
                            'Buffering filtered view · waiting for 5 s of newer samples')
                           if filtered else 'Raw signal · live', color='#607083', size='10pt')
        rate = (len(t)-1)/(t[-1]-t[0])
        self.stats.setText(f'Received: {rate:.1f} samples/s · Sequence gaps: {self.lost} · Latest ADC: {v[-1]:.4f} V · Markers: detected beat energy')

    def closeEvent(self, event):
        if self.updater and not self.updater.close():
            event.ignore(); return
        self.stop()
        if self.recorded_rows:
            self.status.setText('Unsaved recording retained — save before closing')
            event.ignore()
            return
        for key, value in [('mode', self.mode.currentIndex()), ('span', self.span.value()),
                           ('volume', self.volume.value()), ('threshold', self.flat_threshold.value()),
                           ('sound', self.sound_enabled.isChecked()), ('analog_gain', self.analog_gain.value())]:
            self.settings.setValue(key, value)
        self.tone.close()
        self.settings.setValue('calibration_metadata', json.dumps(self.calibration_metadata))
        event.accept()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--replay', type=Path, help='Replay WaveForms CSV or recorded CSV at real speed')
    parser.add_argument('--reset-port', help='Pulse RTS on this COM port before BLE connection, e.g. COM7')
    args = parser.parse_args()
    app = QtWidgets.QApplication(sys.argv[:1]); apply_theme(app)
    w = Window(args.replay, args.reset_port); w.show()
    sys.exit(app.exec())
