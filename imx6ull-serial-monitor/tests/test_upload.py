import contextlib
import hashlib
import io
from pathlib import Path
import re
import shlex
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"host"))
from upload import Replies, BoardError, receiver_command, upload

TAG = "MON_0123456789abcdef"

class Receiver:
    """Transport peer: rejects data before READY or before the last ACK was read."""
    def __init__(self, fail_block=None, corrupt=False):
        self.rx = bytearray()
        self.received = bytearray()
        self.started = False
        self.index = 0
        self.fail_block = fail_block
        self.corrupt = corrupt

    def write(self, data):
        if self.rx:
            raise AssertionError("sender did not wait for peer acknowledgement")
        if not self.started:
            argv = shlex.split(data.decode())
            assert argv[:2] == ["sh", "-c"] and len(argv) == 3
            script = argv[2]
            self.size = int(re.search(r"left=(\d+);",script).group(1))
            self.block = int(re.search(r"want=(\d+);",script).group(1))
            self.digest = re.search(r'\[ "\$1" = \'([a-f0-9]{64})\'',script).group(1)
            self.started = True
            self.rx.extend((TAG+"_READY\r\n").encode())
        else:
            assert len(data) == min(self.block, self.size-len(self.received))
            if self.index == self.fail_block:
                self.rx.extend(("disk write failed\r\n"+TAG+"_FAIL_APPEND\r\n").encode())
                return len(data)
            self.received.extend(data)
            self.rx.extend((f"{TAG}_ACK_{self.index}\r\n").encode())
            self.index += 1
            if len(self.received)==self.size:
                import base64
                digest = hashlib.sha256(base64.b64decode(self.received)).hexdigest()
                status = "_OK" if digest==self.digest and not self.corrupt else "_FAIL_SHA256"
                self.rx.extend((TAG+status+"\r\n").encode())
        return len(data)

    def read(self, count):
        out=bytes(self.rx[:min(count,7)])
        del self.rx[:len(out)]
        return out

class UploadTests(unittest.TestCase):
    def test_complete_multiple_blocks_and_tail(self):
        data=bytes(range(256))*21+b"end";peer=Receiver()
        with contextlib.redirect_stdout(io.StringIO()):
            result=upload(peer,data,TAG,1024,io.BytesIO())
        self.assertEqual(result,hashlib.sha256(data).hexdigest())
        self.assertGreater(peer.index,1)

    def test_board_error_stops_further_writes(self):
        peer=Receiver(fail_block=1)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(BoardError,"FAIL_APPEND"):
            upload(peer,b"a"*6000,TAG,1024,io.BytesIO())
        self.assertEqual(len(peer.received),1024)

    def test_failed_hash_is_not_success(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(BoardError,"FAIL_SHA256"):
            upload(Receiver(corrupt=True),b"a"*300,TAG,1024,io.BytesIO())

    def test_echoed_marker_does_not_match(self):
        peer=Receiver();peer.rx.extend(("root# printf '"+TAG+"_READY'\r\n").encode())
        with self.assertRaisesRegex(TimeoutError,"Last board output"):
            Replies(peer,TAG,io.BytesIO()).wait(TAG+"_READY",.01)

    def test_ack_fragmentation_and_coalescing(self):
        peer=Receiver();peer.rx.extend((TAG+"_ACK_0\r\n"+TAG+"_OK\r\n").encode())
        replies=Replies(peer,TAG,io.BytesIO())
        replies.wait(TAG+"_ACK_0",1);replies.wait(TAG+"_OK",1)

    def test_receiver_command_parameters_and_limit(self):
        cmd=receiver_command(TAG,1680132,1024,"a"*64)
        self.assertLess(len(cmd),3500)
        self.assertEqual(cmd.count("\n"),1)
        with self.assertRaises(ValueError):receiver_command("bad'; touch /x",1,1024,"a"*64)
        with self.assertRaises(ValueError):receiver_command(TAG,1,9000,"a"*64)

    def test_empty_archive_rejected_before_uart(self):
        peer=Receiver()
        with self.assertRaises(ValueError):upload(peer,b"",TAG,1024,io.BytesIO())
        self.assertFalse(peer.started)

if __name__=="__main__":unittest.main(verbosity=2)
