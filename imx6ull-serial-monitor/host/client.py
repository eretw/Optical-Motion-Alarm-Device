import csv
import json
import queue
import re
import sqlite3
import threading
import time
from pathlib import Path
from protocol import Parser, encode, HELLO, CONFIG, SILENCE, STOP, EVENT_ACK, STATUS, REPLY, SAMPLE, EVENT

class Client:
    def __init__(self, transport, output):
        self.transport = transport
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.notifications = queue.Queue(maxsize=200)
        self.write_lock = threading.Lock()
        self.pending_lock = threading.Lock()
        self.waiting = {}
        self.seq = 0
        self.running = True
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _notify(self, kind, value):
        try:
            self.notifications.put_nowait((kind, value))
        except queue.Full:
            try:
                self.notifications.get_nowait()
            except queue.Empty:
                pass
            self.notifications.put_nowait((kind, value))

    def _send(self, kind, payload=b"", wait=False):
        waiter = [threading.Event(), None]
        with self.write_lock:
            if not self.running:
                raise OSError(self.error or "connection closed")
            self.seq = (self.seq + 1) & 0xffff
            seq = self.seq
            with self.pending_lock:
                if seq in self.waiting:
                    raise RuntimeError("sequence still outstanding")
                if wait:
                    self.waiting[seq] = waiter
            packet = encode(kind, seq, payload)
            try:
                n = self.transport.write(packet)
                if n != len(packet):
                    raise OSError("partial serial write")
            except Exception:
                with self.pending_lock:
                    self.waiting.pop(seq, None)
                raise
        return seq, waiter

    def request(self, kind, payload=b"", timeout=2.0):
        seq, waiter = self._send(kind, payload, wait=True)
        try:
            if not waiter[0].wait(timeout):
                raise TimeoutError("board reply timeout; check console ownership, port and firmware")
            if waiter[1] is None:
                raise OSError(self.error or "connection lost")
            if not waiter[1].get("ok"):
                raise ValueError(waiter[1].get("message", "board rejected command"))
            return waiter[1]
        finally:
            with self.pending_lock:
                self.waiting.pop(seq, None)

    def _run(self):
        parser = Parser()
        db = None
        csv_file = None
        heartbeat = time.monotonic()
        last_frame = heartbeat
        fields = ["pc_time", "ms", "als", "ax", "ay", "az", "gx", "gy", "gz", "motion", "valid", "alarm", "dropped", "sensor_errors"]
        try:
            db = sqlite3.connect(self.output / "events.sqlite3")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, received TEXT, payload TEXT)")
            # One CSV per connection; cap file size, then rotate to a new file.
            part = 0
            session = time.time_ns()
            def open_csv():
                f = open(self.output / f"samples-{session}-{part}.csv", "w", newline="", encoding="utf-8")
                writer = csv.DictWriter(f, fields, extrasaction="ignore")
                writer.writeheader()
                return f, writer
            csv_file, writer = open_csv()
            while self.running:
                chunk = self.transport.read(256)
                for f in parser.feed(chunk):
                    try:
                        obj = json.loads(f.payload)
                        if not isinstance(obj, dict):
                            raise ValueError("expected object")
                    except (ValueError, UnicodeError):
                        self._notify("error", "invalid JSON frame ignored")
                        continue
                    last_frame = time.monotonic()
                    if f.type == REPLY:
                        with self.pending_lock:
                            waiter = self.waiting.get(f.seq)
                            if waiter:
                                waiter[1] = obj
                                waiter[0].set()
                        self._notify("reply", obj)
                    elif f.type == SAMPLE:
                        obj["pc_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        writer.writerow(obj)
                        csv_file.flush()
                        self._notify("sample", obj)
                        if csv_file.tell() >= 10*1024*1024:
                            csv_file.close()
                            part += 1
                            csv_file, writer = open_csv()
                    elif f.type == EVENT:
                        event_id = obj.get("id", "")
                        if not isinstance(event_id, str) or not re.fullmatch(r"[0-9a-f]{16}-[0-9a-f]{8}", event_id):
                            self._notify("error", "invalid event id ignored")
                            continue
                        cur = db.execute("INSERT OR IGNORE INTO events VALUES (?, ?, ?)",
                            (event_id, time.strftime("%Y-%m-%d %H:%M:%S"), json.dumps(obj)))
                        db.commit()  # ACK only after durable local commit; duplicates are also ACKed.
                        self._send(EVENT_ACK, event_id)
                        if cur.rowcount:
                            self._notify("event", obj)
                now = time.monotonic()
                if now-heartbeat > 2.0:
                    self._send(STATUS)
                    heartbeat = now
                if now-last_frame > 7.0:
                    raise TimeoutError("no valid board frame for 7 seconds; reconnect after checking the board")
        except Exception as exc:
            if self.running:
                self.error = str(exc)
                self._notify("disconnected", self.error)
        finally:
            self.running = False
            with self.pending_lock:
                for waiter in self.waiting.values():
                    waiter[0].set()
            if csv_file:
                csv_file.close()
            if db:
                db.close()

    def close(self):
        self.running = False
        self.thread.join(timeout=3)
        self.transport.close()
