from PySide6 import QtCore, QtWidgets
from github_releases import latest_release, download_asset

class Job(QtCore.QThread):
    result = QtCore.Signal(object)
    error = QtCore.Signal(str)
    def __init__(self, function, parent):
        super().__init__(parent); self.function = function
    def run(self):
        try: self.result.emit(self.function())
        except Exception as exc: self.error.emit(str(exc))

class ReleasePanel(QtWidgets.QGroupBox):
    def __init__(self, settings, selected):
        super().__init__('GitHub release · optional')
        self.settings=settings; self.selected=selected; self.job=None; self.assets=[]
        layout=QtWidgets.QVBoxLayout(self)
        self.repo=QtWidgets.QLineEdit(str(settings.value('repository','')))
        self.repo.setPlaceholderText('owner/repository — public repository')
        layout.addWidget(self.repo)
        self.check=QtWidgets.QPushButton('Check latest release'); self.check.clicked.connect(self.fetch); layout.addWidget(self.check)
        self.info=QtWidgets.QLabel('Or select a local firmware file above.'); self.info.setWordWrap(True); layout.addWidget(self.info)
        self.assets_box=QtWidgets.QComboBox(); layout.addWidget(self.assets_box)
        self.download=QtWidgets.QPushButton('Download selected firmware'); self.download.setEnabled(False)
        self.download.clicked.connect(self.fetch_asset); layout.addWidget(self.download)
    def busy(self):
        return self.job is not None and self.job.isRunning()
    def run_job(self, function, success):
        if self.busy(): return
        self.check.setEnabled(False); self.download.setEnabled(False); self.repo.setEnabled(False)
        self.job=Job(function,self); self.job.result.connect(success)
        self.job.error.connect(lambda error:self.info.setText(error))
        self.job.finished.connect(self.finished_job); self.job.start()
    def finished_job(self):
        self.check.setEnabled(True); self.repo.setEnabled(True); self.download.setEnabled(bool(self.assets))
    def fetch(self):
        repo=self.repo.text().strip(); self.assets=[]; self.assets_box.clear()
        self.settings.setValue('repository',repo); self.info.setText('Checking release…')
        self.run_job(lambda:latest_release(repo),self.found)
    def found(self, release):
        self.assets=release['assets']; self.info.setText('Latest release: '+release['tag'])
        self.info.setToolTip(release['notes'][:6000])
        for asset in self.assets: self.assets_box.addItem(asset['name'])
    def fetch_asset(self):
        if not self.assets: return
        asset=self.assets[self.assets_box.currentIndex()]
        cache=QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.CacheLocation)+'/firmware'
        self.info.setText('Downloading and checking SHA-256 and ESP32-S3 target…')
        self.run_job(lambda:download_asset(asset,cache),self.downloaded)
    def downloaded(self,path):
        self.info.setText('Firmware downloaded and checked. It has not been flashed.')
        self.selected(path)
