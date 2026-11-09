"""Shared desktop typography, spacing and colour palette."""
from PySide6 import QtWidgets, QtGui


def apply_theme(app):
    app.setStyle('Fusion')
    app.setFont(QtGui.QFont('Segoe UI', 10))
    app.setStyleSheet('''
    QWidget { background: #f4f6f8; color: #202d3b; }
    QMainWindow { background: #f4f6f8; }
    QLabel { background: transparent; }
    QLabel#title { font-size: 24px; font-weight: 600; }
    QLabel#muted { color: #607083; }
    QGroupBox { background: white; border: 1px solid #dce2e8;
      border-radius: 6px; margin-top: 20px; padding: 18px 12px 12px; font-weight: 600; }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
    QPushButton { background: white; border: 1px solid #bbc6d1; border-radius: 4px;
      padding: 8px 14px; min-height: 18px; }
    QPushButton:hover { background: #eaf0f6; border-color: #758ca3; }
    QPushButton:pressed { background: #dce7f1; }
    QPushButton#primary { background: #185c91; color: white; border-color: #185c91; font-weight: 600; }
    QPushButton#primary:hover { background: #124b78; }
    QPushButton:disabled { color: #8a96a3; background: #edf0f3; border-color: #dce2e8; }
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #bbc6d1;
      border-radius: 4px; padding: 7px; min-height: 18px; selection-background-color: #185c91; }
    QLineEdit:focus, QComboBox:focus { border-color: #185c91; }
    QPlainTextEdit { background: #17222e; color: #d7e1eb; border: none; border-radius: 4px;
      padding: 10px; font-family: Consolas, monospace; font-size: 12px; }
    QProgressBar { border: 1px solid #dce2e8; border-radius: 4px; background: white;
      text-align: center; min-height: 22px; }
    QProgressBar::chunk { background: #63a5d2; }
    QCheckBox { spacing: 8px; }
    QStatusBar { background: #e9eef3; }
    ''')


def heading(layout, title, subtitle):
    label = QtWidgets.QLabel(title); label.setObjectName('title'); layout.addWidget(label)
    label = QtWidgets.QLabel(subtitle); label.setObjectName('muted'); label.setWordWrap(True)
    layout.addWidget(label)
