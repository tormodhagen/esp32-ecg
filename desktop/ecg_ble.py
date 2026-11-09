"""BLE wire format shared with src/main.cpp: packed little-endian IIh records."""
import struct

SERVICE_UUID = 'c47e1000-17c4-4b56-9be5-125cece00001'
DATA_UUID = 'c47e1001-17c4-4b56-9be5-125cece00001'
RECORD = struct.Struct('<IIh')


def decode_packet(data, decoder):
    if not data or len(data) % RECORD.size:
        raise ValueError('Ugyldig BLE-pakkelengde')
    rows = []
    for seq, us, raw in RECORD.iter_unpack(data):
        row = decoder.feed(f'E,{seq},{us},{raw}')
        if row is not None:
            rows.append(row)
    return rows
