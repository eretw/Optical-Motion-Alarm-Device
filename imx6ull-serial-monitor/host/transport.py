"""Serial transport plus deterministic in-process board simulator (no hardware required)."""
import json
import math
import sys
import time
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
from protocol import Parser, encode, HELLO, CONFIG, SILENCE, STOP, EVENT_ACK, STATUS, REPLY, SAMPLE, EVENT

def serial_ports():
    from serial.tools import list_ports
    return [(p.device, p.description, p.hwid) for p in list_ports.comports()]

def open_serial(port):
    import serial
    return serial.Serial(port, baudrate=115200, bytesize=8, parity="N", stopbits=1,
                         timeout=0.1, write_timeout=0.5, xonxoff=False, rtscts=False, dsrdtr=False)

class SimTransport:
    """Behavior demo, not a substitute for running the real ARM program."""
    def __init__(self):
        self.lock = threading.Lock()
        self.parser = Parser()
        self.pending = bytearray()
        self.closed = False
        self.connected = False
        self.start = time.monotonic()
        self.due = self.start
        self.period, self.light, self.motion = 200, 3000, 4000
        self.seq = 0
        self.tick = 0
        self.events = {}
        self.silenced = False
        self.active = False

    def _send(self, kind, seq, obj):
        self.pending.extend(encode(kind, seq, json.dumps(obj, separators=(",", ":"))))

    def write(self, data):
        with self.lock:
            if self.closed:
                raise OSError("simulator closed")
            for f in self.parser.feed(data):
                result = {"ok": True, "command": f.type, "message": "ok"}
                if f.type == HELLO:
                    self.connected = True
                    result["message"] = "monitor/1 PYTHON SIMULATOR"
                elif f.type == CONFIG:
                    try:
                        p, l, m = [int(v) for v in f.payload.decode("ascii").split(",")]
                        if not (200 <= p <= 10000 and 0 <= l <= 65535 and 1 <= m <= 65535):
                            raise ValueError()
                        self.period, self.light, self.motion = p, l, m
                    except (ValueError, UnicodeError):
                        result = {"ok": False, "message": "invalid configuration"}
                elif f.type == SILENCE:
                    self.silenced = True
                elif f.type == STOP:
                    self.connected = False
                    result["message"] = "simulation stopped"
                elif f.type == EVENT_ACK:
                    self.events.pop(f.payload.decode("ascii"), None)
                elif f.type == STATUS:
                    result.update(period_ms=self.period, light_raw=self.light, motion_raw=self.motion,
                                  pending=len(self.events), storage_errors=0, tx_errors=0)
                else:
                    result = {"ok": False, "message": "unknown command"}
                self._send(REPLY, f.seq, result)
        return len(data)

    def read(self, count):
        time.sleep(0.02)
        with self.lock:
            if self.closed:
                raise OSError("simulator closed")
            now = time.monotonic()
            if self.connected and now >= self.due:
                self.due = now + self.period / 1000
                self.tick += 1
                self.seq = (self.seq + 1) & 0xffff
                als = 4000 if 20 <= self.tick % 30 < 23 else 120
                motion = 6000 if self.tick % 25 == 0 else 50
                active = als > self.light or motion > self.motion
                if not active:
                    self.silenced = False
                ms = int((now-self.start)*1000)
                if active and not self.active:
                    event_id = f"{int(self.start*1000000):016x}-{self.tick:08x}"
                    self.events[event_id] = dict(id=event_id, ms=ms, als=als, motion=motion)
                self.active = active
                self._send(SAMPLE, self.seq, dict(ms=ms, als=als, ax=int(math.sin(self.tick/5)*100),
                    ay=0, az=16384, gx=0, gy=0, gz=0, motion=motion, valid=1,
                    alarm=int(active and not self.silenced), dropped=0, sensor_errors=0))
                if self.events:
                    self._send(EVENT, self.seq, next(iter(self.events.values())))
            out = bytes(self.pending[:count])
            del self.pending[:count]
            return out

    def close(self):
        with self.lock:
            self.closed = True
