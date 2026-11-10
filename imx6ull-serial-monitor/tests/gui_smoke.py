"""Hidden Tk smoke test. Does not connect to real serial hardware."""
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"host"))
import tkinter as tk
from dashboard import Dashboard
root=tk.Tk();root.withdraw();app=Dashboard(root)
def wait_for(predicate, seconds=5):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        root.update();time.sleep(.02)
        if predicate():return
    raise AssertionError("GUI condition timeout")
try:
    app.connect();wait_for(lambda:app.client is not None and not app.busy)
    wait_for(lambda:"16384" in app.sample.get())
    app.cfg[1].set("100");app.configure();wait_for(lambda:not app.busy)
    wait_for(lambda:"报警: 1" in app.sample.get())
    app.disconnect();wait_for(lambda:not app.busy)
    print("PASS: Tk create/connect/sample/config/alarm/disconnect")
finally:
    app.close()
