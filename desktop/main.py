"""Single entry point for the monitor and its bundled update subprocess."""
import os
import sys
from pathlib import Path

def main():
    if '--ota-worker' in sys.argv:
        sys.argv.remove('--ota-worker')
        log = os.environ.get('ECG_OTA_LOG')
        if log:
            sys.stdout = sys.stderr = open(log, 'w', encoding='utf-8', buffering=1)
        import runpy
        runpy.run_module('ota_update', run_name='__main__')
        return
    import argparse
    from PySide6 import QtWidgets
    from ui_theme import apply_theme
    from live_ecg import Window
    parser = argparse.ArgumentParser()
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--reset-port')
    args = parser.parse_args()
    app = QtWidgets.QApplication(sys.argv[:1]); apply_theme(app)
    window = Window(args.replay, args.reset_port); window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
