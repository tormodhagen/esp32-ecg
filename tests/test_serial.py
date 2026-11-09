import unittest
from unittest.mock import patch
from live_ecg import open_ecg_serial

class SerialStartupTests(unittest.TestCase):
    def test_control_lines_released_before_open(self):
        events = []
        class FakeSerial:
            def __init__(self, **kwargs):
                self.options = kwargs
                self.dtr = self.rts = True
                self.port = kwargs['port']
            def open(self):
                events.append((self.port, self.dtr, self.rts, self.options))
        with patch('live_ecg.serial.Serial', FakeSerial):
            open_ecg_serial('COM7')
        port, dtr, rts, options = events[0]
        self.assertEqual(port, 'COM7')
        self.assertFalse(dtr)
        self.assertFalse(rts)
        self.assertIsNone(options['port'])
        self.assertFalse(options['rtscts'])
        self.assertFalse(options['dsrdtr'])
