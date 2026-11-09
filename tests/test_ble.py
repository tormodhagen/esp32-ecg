import asyncio
import struct
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ecg_ble import decode_packet, SERVICE_UUID
from ecg_signal import Decoder

class BleProtocolTests(unittest.TestCase):
    def test_raw_and_gap_and_wrap(self):
        d = Decoder()
        rows = decode_packet(struct.pack('<IIhIIh', 10, 0xfffffff0, -32768,
                                         13, 1000, 32767), d)
        self.assertEqual(rows[0][4], -32768)
        self.assertEqual(rows[1][5], 2)
        self.assertAlmostEqual(rows[1][0], .001016)
        self.assertFalse(rows[1][-1])
        self.assertEqual(decode_packet(struct.pack('<IIh', 13, 1000, 32767), d), [])

    def test_reject_partial(self):
        with self.assertRaises(ValueError):
            decode_packet(b'123', Decoder())

    def test_reader_stream_and_disconnect(self):
        from live_ecg import Reader
        device = SimpleNamespace(address='AA:BB')
        class Scanner:
            @staticmethod
            async def discover(**kwargs):
                return {'AA:BB': (device, SimpleNamespace(service_uuids=[SERVICE_UUID]))}
        class Client:
            mtu_size = 185
            services = SimpleNamespace(get_characteristic=lambda _: None)
            def __init__(self, device, **kwargs):
                self.disconnect = kwargs['disconnected_callback']
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def start_notify(self, uuid, callback):
                callback(None, struct.pack('<IIhIIh', 1, 100, 200, 2, 1263, 201))
                asyncio.get_running_loop().call_later(.01, self.disconnect, self)
        reader = Reader(ble=True)
        received = []
        reader.batch.connect(received.extend)
        with patch.dict(sys.modules, bleak=SimpleNamespace(BleakScanner=Scanner, BleakClient=Client)):
            asyncio.run(reader.run_ble())
        self.assertEqual(len(received), 2)
        self.assertEqual(received[1][4], 201)
        self.assertAlmostEqual(received[1][0], .001163)

class BleStatusTests(unittest.TestCase):
    def test_no_samples_reports_adc_status(self):
        from live_ecg import Reader
        import itertools
        device = SimpleNamespace(address='AA:BB')
        class Scanner:
            @staticmethod
            async def discover(**kwargs):
                return {'AA:BB': (device, SimpleNamespace(service_uuids=[SERVICE_UUID]))}
        class Client:
            mtu_size = 185
            is_connected = True
            services = SimpleNamespace(get_characteristic=lambda _: object())
            def __init__(self, device, **kwargs):
                self.disconnect = kwargs['disconnected_callback']
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def start_notify(self, uuid, callback): pass
            async def read_gatt_char(self, uuid):
                self.disconnect(self)
                return b'#ECG2 adc=waiting for ADS1115 rdy=0'
        reader = Reader(ble=True)
        messages = []
        reader.message.connect(messages.append)
        clock = itertools.count(0, 3)
        with patch.dict(sys.modules, bleak=SimpleNamespace(BleakScanner=Scanner, BleakClient=Client)):
            with patch('live_ecg.time', SimpleNamespace(monotonic=lambda: next(clock))):
                asyncio.run(reader.run_ble())
        self.assertTrue(any('waiting for ADS1115' in msg for msg in messages))

if __name__ == '__main__': unittest.main()
