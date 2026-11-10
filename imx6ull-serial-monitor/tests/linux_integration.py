"""Run on Ubuntu/WSL Linux AFTER: make -C board CROSS_COMPILE=
Uses a PTY to test the real C application with --mock; does not touch a physical UART.
"""
import os
import pty
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
from client import Client
from protocol import HELLO, CONFIG, STATUS, STOP

class PTYTransport:
    def __init__(self,fd):self.fd=fd
    def read(self,n):return os.read(self.fd,n) if select.select([self.fd],[],[],.1)[0] else b""
    def write(self,b):return os.write(self.fd,b)
    def close(self):pass

def main():
    with tempfile.TemporaryDirectory() as tmp:
        state=Path(tmp)/"state";logs=Path(tmp)/"pc"
        for first in (True,False):
            master,slave=pty.openpty()
            proc=subprocess.Popen([str(ROOT/"board/monitor"),"--serial",os.ttyname(slave),"--state",str(state),"--mock"],stderr=subprocess.PIPE)
            client=None
            try:
                time.sleep(.25)
                if proc.poll() is not None:raise RuntimeError(proc.stderr.read().decode())
                client=Client(PTYTransport(master),logs)
                client.request(HELLO)
                if first:client.request(CONFIG,"250,1,4000")
                status=client.request(STATUS)
                assert status["period_ms"]==250,status
                time.sleep(1)
                client.request(STOP)
                assert proc.wait(3)==0
            finally:
                if client:client.close()
                if proc.poll() is None:proc.terminate();proc.wait(3)
                os.close(master);os.close(slave)
        print("PASS: real C process PTY handshake/config/persistence/restart/stop")
if __name__=="__main__":main()
