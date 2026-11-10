"""Wire format shared with common/protocol.c. All multibyte fields are little-endian."""
import binascii
import struct
import time
from dataclasses import dataclass

HELLO, CONFIG, SILENCE, STOP, EVENT_ACK, STATUS = range(1, 7)
REPLY, SAMPLE, EVENT = 0x80, 0x81, 0x82
MAX_PAYLOAD = 256

@dataclass(frozen=True)
class Frame:
    type: int
    seq: int
    payload: bytes

def encode(kind, seq, payload=b""):
    if isinstance(payload, str):
        payload = payload.encode("ascii")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload exceeds 256 bytes")
    body = struct.pack("<BBHH", 1, kind, seq, len(payload)) + payload
    return b"\xa5\x5a" + body + struct.pack("<H", binascii.crc_hqx(body, 0xffff))

class Parser:
    def __init__(self):
        self.buf = bytearray()
        self.last = 0.0
        self.bad_crc = 0
        self.bad_header = 0

    def feed(self, data):
        now = time.monotonic()
        if self.last and now - self.last > 1.0:
            self.buf.clear()
        self.last = now
        frames = []
        # Byte-wise bounded buffering, including arbitrarily large caller chunks.
        for byte in data:
            self.buf.append(byte)
            while self.buf:
                if self.buf[0] != 0xa5 or (len(self.buf) >= 2 and self.buf[1] != 0x5a):
                    del self.buf[0]
                    continue
                if len(self.buf) < 8:
                    break
                ver, kind, seq, size = struct.unpack_from("<BBHH", self.buf, 2)
                if ver != 1 or size > MAX_PAYLOAD:
                    self.bad_header += 1
                    del self.buf[0]
                    continue
                if len(self.buf) < size + 10:
                    break
                crc, = struct.unpack_from("<H", self.buf, 8 + size)
                if crc != binascii.crc_hqx(self.buf[2:8+size], 0xffff):
                    self.bad_crc += 1
                    del self.buf[0]
                    continue
                frames.append(Frame(kind, seq, bytes(self.buf[8:8+size])))
                del self.buf[:size+10]
        return frames
