"""Desktop front end for the BLE-triggered OTA worker."""
import os
from pathlib import Path
import re
import sys
from PySide6 import QtCore, QtWidgets
from ui_theme import apply_theme, heading


class OtaWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('ECG Firmware Updater · XIAO ESP32-S3'); self.resize(860, 760)
        self.setMinimumSize(540, 480)
        self.setWindowFlag(QtCore.Qt.Window, True)
        self.process = None
        self.log_path = None; self.log_offset = 0
        self.log_timer = QtCore.QTimer(self); self.log_timer.setInterval(150)
        self.log_timer.timeout.connect(self.read_output)
        self.settings = QtCore.QSettings('ECG Tools', 'Firmware Updater')
        main = QtWidgets.QWidget(); self.setCentralWidget(main)
        outer = QtWidgets.QVBoxLayout(main); outer.setContentsMargins(20, 16, 20, 16); outer.setSpacing(10)
        heading(outer, 'Firmware update', 'XIAO ESP32-S3 · Bluetooth or Wi-Fi')
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame); outer.addWidget(scroll, 1)
        settings_widget = QtWidgets.QWidget(); scroll.setWidget(settings_widget)
        layout = QtWidgets.QVBoxLayout(settings_widget); layout.setContentsMargins(0, 0, 8, 0); layout.setSpacing(10)
        layout.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
        box = QtWidgets.QGroupBox('Source'); layout.addWidget(box)
        form = QtWidgets.QFormLayout(box); form.setSpacing(12)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.project = QtWidgets.QLineEdit(self.settings.value('project', str(Path(__file__).resolve().parents[1] / 'firmware')))
        form.addRow('Project folder', self.path_row(self.project, True))
        self.environment = QtWidgets.QLineEdit(self.settings.value('environment', 'esp32dev'))
        form.addRow('Build environment', self.environment)
        target = QtWidgets.QLabel('ESP32-S3 image only · min_spiffs OTA slot: 1.875 MiB')
        target.setWordWrap(True); form.addRow('Target', target)
        self.build = QtWidgets.QCheckBox('Build the project before uploading'); self.build.setChecked(False)
        form.addRow('', self.build)
        self.image = QtWidgets.QLineEdit(); self.image.setPlaceholderText('Select an application firmware.bin')
        self.image_row = self.path_row(self.image, False); form.addRow('Firmware file', self.image_row)
        self.build.toggled.connect(lambda checked: self.image_row.setEnabled(not checked))
        self.image_row.setEnabled(True)
        self.host = QtWidgets.QLineEdit(); self.host.setPlaceholderText('Leave empty for BLE, or enter ecg.local / IP')
        form.addRow('Wi-Fi device address', self.host)
        self.address = QtWidgets.QLineEdit(); self.address.setPlaceholderText('Automatic discovery')
        form.addRow('BLE address', self.address)
        self.token = QtWidgets.QLineEdit(str(self.settings.value('device_token', ''))); self.token.setEchoMode(QtWidgets.QLineEdit.Password)
        self.token.setPlaceholderText('Read from project/src/ota_config.h'); form.addRow('Device token', self.token)
        forget = QtWidgets.QPushButton('Forget saved token'); form.addRow('', forget)
        forget.clicked.connect(lambda: (self.token.clear(), self.settings.remove('device_token')))
        self.inputs = box
        from release_gui import ReleasePanel
        self.releases = ReleasePanel(self.settings, self.use_release)
        layout.addWidget(self.releases)
        toggle = QtWidgets.QPushButton('Advanced tool paths'); toggle.setCheckable(True); layout.addWidget(toggle)
        advanced = QtWidgets.QGroupBox('Tool paths · optional'); layout.addWidget(advanced)
        advanced.setVisible(False); toggle.toggled.connect(advanced.setVisible)
        f = QtWidgets.QFormLayout(advanced)
        f.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        self.pio = QtWidgets.QLineEdit(self.settings.value('pio', '')); self.pio.setPlaceholderText('Detect PlatformIO automatically')
        self.espota = QtWidgets.QLineEdit(self.settings.value('espota', '')); self.espota.setPlaceholderText('Detect installed framework/tools/espota.py')
        f.addRow('PlatformIO', self.path_row(self.pio, False)); f.addRow('espota.py', self.path_row(self.espota, False))
        self.advanced = advanced
        layout.addStretch()
        layout = outer
        hint = QtWidgets.QLabel('Keep the device powered throughout the transfer. Monitoring is disconnected before updating.')
        hint.setWordWrap(True); hint.setObjectName('muted'); layout.addWidget(hint)
        self.state = QtWidgets.QLabel('Ready'); layout.addWidget(self.state)
        self.progress = QtWidgets.QProgressBar(); self.progress.setValue(0); layout.addWidget(self.progress)
        row = QtWidgets.QHBoxLayout(); layout.addLayout(row)
        self.start = QtWidgets.QPushButton('Update firmware'); self.start.setObjectName('primary'); self.start.clicked.connect(self.launch); row.addWidget(self.start)
        self.cancel = QtWidgets.QPushButton('Cancel'); self.cancel.setEnabled(False); self.cancel.clicked.connect(self.cancel_update); row.addWidget(self.cancel)
        row.addStretch()
        copy = QtWidgets.QPushButton('Copy log'); copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.log.toPlainText())); row.addWidget(copy)
        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(6000); self.log.setMinimumHeight(70); self.log.setMaximumHeight(120); layout.addWidget(self.log)
        self.pending = ''; self.cancelled = False

    def use_release(self, path):
        self.build.setChecked(False)
        self.image.setText(path)
        self.state.setText('Release downloaded and checked. Select Update firmware to install.')

    def path_row(self, edit, directory):
        w = QtWidgets.QWidget(); row = QtWidgets.QHBoxLayout(w); row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1); button = QtWidgets.QPushButton('Browse…'); row.addWidget(button)
        def choose():
            path = (QtWidgets.QFileDialog.getExistingDirectory(self, 'Project folder', edit.text()) if directory else
                    QtWidgets.QFileDialog.getOpenFileName(self, 'Select file', edit.text())[0])
            if path: edit.setText(path)
        button.clicked.connect(choose); return w

    def launch(self):
        if self.releases.busy():
            QtWidgets.QMessageBox.information(self, 'Download in progress', 'Wait for the release download to finish.'); return
        project = Path(self.project.text().strip())
        if (project/'firmware/platformio.ini').is_file(): project = project/'firmware'
        if self.build.isChecked() and not (project/'platformio.ini').is_file():
            QtWidgets.QMessageBox.warning(self, 'Select project', 'Choose the firmware project folder containing platformio.ini.'); return
        if not self.build.isChecked() and not Path(self.image.text()).is_file():
            QtWidgets.QMessageBox.warning(self, 'Select firmware', 'Choose an application firmware.bin.'); return
        token = self.token.text().strip()
        if token and not re.fullmatch('[A-Za-z0-9]{16}', token):
            QtWidgets.QMessageBox.warning(self, 'Device token', 'Enter the 16-character alphanumeric token from the running firmware.'); return
        if not token and not (project/'src/ota_config.h').is_file():
            QtWidgets.QMessageBox.warning(self, 'Device token', 'Enter the token from the running firmware, or select the firmware project containing ota_config.h.'); return
        if self.parent() and hasattr(self.parent(), 'prepare_update'):
            if not self.parent().prepare_update(): return
        args = ['--project', str(project.resolve()), '--environment', self.environment.text().strip()]
        for flag, edit in [('--host', self.host), ('--address', self.address), ('--pio', self.pio), ('--espota', self.espota)]:
            if edit.text().strip(): args += [flag, edit.text().strip()]
        if not self.build.isChecked(): args += ['--firmware', str(Path(self.image.text()).resolve())]
        if getattr(sys, 'frozen', False):
            program = sys.executable; args.insert(0, '--ota-worker')
        else:
            program = sys.executable; args.insert(0, str(Path(__file__).with_name('main.py'))); args.insert(1, '--ota-worker')
        self.process = QtCore.QProcess(self)
        env = QtCore.QProcessEnvironment.systemEnvironment(); env.insert('PYTHONUNBUFFERED', '1'); env.insert('PYTHONIOENCODING', 'utf-8')
        if token:
            env.insert('ECG_OTA_TOKEN', token)
            self.settings.setValue('device_token', token)
        else: env.remove('ECG_OTA_TOKEN')
        import tempfile
        fd, self.log_path = tempfile.mkstemp(prefix='ecg-ota-', suffix='.log'); os.close(fd)
        self.log_offset = 0; env.insert('ECG_OTA_LOG', self.log_path)
        self.process.setProcessEnvironment(env); self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.done); self.process.errorOccurred.connect(self.process_error)
        self.log.clear(); self.pending = ''; self.cancelled = False
        self.progress.setRange(0, 0); self.state.setText('Building firmware…' if self.build.isChecked() else 'Connecting…')
        self.set_busy(True)
        for key, edit in [('project', self.project), ('pio', self.pio), ('espota', self.espota), ('environment', self.environment)]: self.settings.setValue(key, edit.text())
        self.process.start(program, args)
        self.log_timer.start()

    def set_busy(self, busy):
        self.start.setEnabled(not busy); self.cancel.setEnabled(busy)
        self.inputs.setEnabled(not busy); self.advanced.setEnabled(not busy); self.releases.setEnabled(not busy)

    def read_output(self):
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace') if self.process else ''
        if self.log_path and Path(self.log_path).exists():
            with open(self.log_path, 'rb') as stream:
                stream.seek(self.log_offset); text += stream.read().decode('utf-8', errors='replace'); self.log_offset = stream.tell()
        self.pending += text
        pieces = re.split('[\r\n]', self.pending); self.pending = pieces.pop()
        for line in pieces:
            if not line: continue
            self.log.appendPlainText(line)
            match = re.search(r'Uploading:.*?([0-9]+)%', line)
            if match:
                self.progress.setRange(0, 100); self.progress.setValue(int(match[1])); self.state.setText('Transferring firmware…')
            elif 'Searching for ESP32' in line: self.state.setText('Finding device over Bluetooth…')
            elif 'Waiting for update mode' in line: self.state.setText('Waiting for Wi-Fi…')
            elif 'Authenticating' in line: self.state.setText('Authenticating…')

    def done(self, code, status):
        self.log_timer.stop(); self.read_output()
        if self.log_path:
            Path(self.log_path).unlink(missing_ok=True); self.log_path = None
        if self.pending: self.log.appendPlainText(self.pending); self.pending = ''
        self.set_busy(False); self.progress.setRange(0, 100)
        ok = code == 0 and status == QtCore.QProcess.NormalExit and not self.cancelled
        self.progress.setValue(100 if ok else 0)
        self.state.setText('Upload complete · reconnect the monitor to verify.' if ok else
                           'Cancelled · device state not verified.' if self.cancelled else 'Update failed · see the log for details.')

    def process_error(self, error):
        if error == QtCore.QProcess.FailedToStart:
            self.set_busy(False); self.progress.setRange(0, 100); self.progress.setValue(0)
            self.state.setText('Could not start the integrated update process.')
            self.log.appendPlainText(self.process.errorString())

    def cancel_update(self):
        answer = QtWidgets.QMessageBox.question(self, 'Cancel update?', 'Interrupt the current operation? Keep the ESP32 powered; its state will need checking.')
        if answer != QtWidgets.QMessageBox.Yes: return
        self.cancelled = True
        # On Windows terminate the process tree, including a PlatformIO build.
        if sys.platform == 'win32':
            import subprocess
            subprocess.run(['taskkill', '/PID', str(self.process.processId()), '/T', '/F'], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else: self.process.kill()

    def closeEvent(self, event):
        if self.releases.busy():
            QtWidgets.QMessageBox.information(self, 'Download in progress', 'Wait for the download to finish before closing.'); event.ignore(); return
        if self.process and self.process.state() != QtCore.QProcess.NotRunning:
            QtWidgets.QMessageBox.information(self, 'Update in progress', 'Wait for completion or cancel the update before closing.'); event.ignore()
        else: event.accept()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv); apply_theme(app)
    window = OtaWindow(); window.show(); sys.exit(app.exec())
