"""Win11 CLI: python host/monitor.py --simulate --seconds 12"""
import argparse
import queue
import time
from pathlib import Path
from client import Client
from transport import SimTransport, open_serial, serial_ports
from protocol import HELLO, CONFIG, SILENCE, STOP, STATUS

def main():
    p = argparse.ArgumentParser(description="ALPHA i.MX6ULL USB serial monitor, 115200 8N1")
    p.add_argument("--list", action="store_true")
    p.add_argument("--simulate", action="store_true")
    p.add_argument("--port", help="Actual CH340 COM port, e.g. COM7 (not the ELTIMA virtual pair)")
    p.add_argument("--seconds", type=float, default=0, help="0 = run until Ctrl+C")
    p.add_argument("--set", metavar="PERIOD,LIGHT,MOTION", help="e.g. 200,3000,4000")
    p.add_argument("--silence", action="store_true")
    p.add_argument("--stop", action="store_true", help="Ask board application to exit, then restore terminal")
    p.add_argument("--output", default=str(Path(__file__).resolve().parents[1]/"logs"))
    a = p.parse_args()
    if a.list:
        for port, name, hwid in serial_ports():
            print(f"{port}: {name} [{hwid}]")
        return
    if bool(a.simulate) == bool(a.port):
        p.error("choose exactly one of --simulate and --port")
    if a.seconds < 0:
        p.error("seconds must be nonnegative")
    c = Client(SimTransport() if a.simulate else open_serial(a.port), a.output)
    try:
        print(c.request(HELLO))
        if a.set:
            print(c.request(CONFIG, a.set))
        if a.silence:
            print(c.request(SILENCE))
        if a.stop:
            print(c.request(STOP))
            return
        print(c.request(STATUS))
        start = time.monotonic()
        while c.running and (not a.seconds or time.monotonic()-start < a.seconds):
            try:
                kind, value = c.notifications.get(timeout=0.2)
                print(kind, value)
            except queue.Empty:
                pass
        if c.error:
            raise RuntimeError(c.error)
    finally:
        c.close()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
