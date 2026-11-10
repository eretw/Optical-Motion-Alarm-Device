import ctypes as C
import importlib.util
import json
import os
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import time
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"host"))
from protocol import *
from transport import SimTransport
from client import Client

class ProtocolTests(unittest.TestCase):
    def test_crc_reference(self):
        import binascii
        self.assertEqual(binascii.crc_hqx(b"123456789",0xffff),0x29b1)

    def test_fragmentation_and_coalescing(self):
        messages=[encode(1,1),encode(CONFIG,2,"200,3000,4000"),encode(SAMPLE,3,b"x"*256)]
        p=Parser();out=[]
        for b in b"boot log\r\n"+b"".join(messages):out+=p.feed(bytes([b]))
        self.assertEqual([(x.type,x.seq,len(x.payload)) for x in out],[(1,1,0),(2,2,13),(SAMPLE,3,256)])

    def test_bad_crc_and_resync(self):
        bad=bytearray(encode(CONFIG,42,"200,3000,4000"));bad[-1]^=1
        p=Parser();out=p.feed(bad+encode(HELLO,99))
        self.assertEqual([f.seq for f in out],[99]);self.assertEqual(p.bad_crc,1)

    def test_invalid_length_bounded(self):
        p=Parser();out=p.feed(b"\xa5\x5a\x01\x01\x00\x00\xff\xff"+encode(HELLO,1))
        self.assertEqual(len(out),1);self.assertEqual(p.bad_header,1)
        p.feed(b"x"*100000);self.assertLessEqual(len(p.buf),266)

    def test_timeout_recovery(self):
        p=Parser();p.feed(encode(HELLO,3,b"x"*256)[:10]);p.last-=2
        self.assertEqual(p.feed(encode(HELLO,4))[0].seq,4)

    def test_payload_limit(self):
        with self.assertRaises(ValueError):encode(SAMPLE,1,b"a"*257)

class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        library=ROOT/"build"/("mon_core.dll" if os.name=="nt" else "libmon_core.so")
        if os.name=="nt" and not library.exists():library=ROOT/"release/windows/mon_core.dll"
        if not library.exists():raise unittest.SkipTest("Native C test library not built")
        cls.lib=C.CDLL(str(library))
        class ParserC(C.Structure):
            _fields_=[("data",C.c_ubyte*266),("used",C.c_size_t),("bad_crc",C.c_uint32),("bad_header",C.c_uint32)]
        class FrameC(C.Structure):
            _fields_=[("type",C.c_ubyte),("seq",C.c_uint16),("len",C.c_uint16),("payload",C.c_ubyte*257)]
        class ConfigC(C.Structure):
            _fields_=[("period",C.c_uint),("light",C.c_uint),("motion",C.c_uint)]
        cls.P,cls.F,cls.Config=ParserC,FrameC,ConfigC
        cls.lib.mon_crc.argtypes=[C.c_void_p,C.c_size_t];cls.lib.mon_crc.restype=C.c_uint16
        cls.lib.mon_encode.argtypes=[C.c_void_p,C.c_ubyte,C.c_uint16,C.c_void_p,C.c_size_t]
        cls.lib.mon_encode.restype=C.c_size_t
        cls.lib.mon_feed.argtypes=[C.POINTER(ParserC),C.c_ubyte,C.POINTER(FrameC)]
        cls.lib.config_parse.argtypes=[C.c_char_p,C.POINTER(ConfigC)]

    def test_c_python_wire_equivalence(self):
        rng=random.Random(6)
        for n in range(1000):
            data=bytes(rng.randrange(256) for _ in range(rng.randrange(257)))
            kind=rng.randrange(256);seq=rng.randrange(65536);buf=C.create_string_buffer(266)
            size=self.lib.mon_encode(buf,kind,seq,data,len(data))
            self.assertEqual(buf.raw[:size],encode(kind,seq,data))
            parser=self.P();frame=self.F();got=[]
            for b in b"log\r\n"+buf.raw[:size]:
                if self.lib.mon_feed(C.byref(parser),b,C.byref(frame)):
                    got.append((frame.type,frame.seq,bytes(frame.payload[:frame.len])))
            self.assertEqual(got,[(kind,seq,data)])
        self.assertEqual(self.lib.mon_crc(b"123456789",9),0x29b1)

    def test_c_crc_and_length_recovery(self):
        bad=bytearray(encode(1,2,b"hello"));bad[-2]^=4
        stream=b"\xa5\x5a\x01\x02\x00\x00\xff\xff"+bad+encode(1,88)
        p=self.P();f=self.F();got=[]
        for b in stream:
            if self.lib.mon_feed(C.byref(p),b,C.byref(f)):got.append(f.seq)
        self.assertEqual(got,[88]);self.assertEqual(p.bad_header,1);self.assertEqual(p.bad_crc,1)

    def test_config_limits_and_overflow(self):
        for bad in [b"199,1,1",b"10001,1,1",b"200,65536,1",b"200,1,0",b"-1,1,1",
                    b"4294967496,1,1",b"200,1,1x",b"200,1,1\n",b"200,,1",b" 200,1,1"]:
            c=self.Config(999,888,777)
            self.assertNotEqual(self.lib.config_parse(bad,C.byref(c)),0,bad)
            self.assertEqual((c.period,c.light,c.motion),(999,888,777))
        c=self.Config();self.assertEqual(self.lib.config_parse(b"200,0,65535",C.byref(c)),0)
        self.assertEqual((c.period,c.light,c.motion),(200,0,65535))

class ClientTests(unittest.TestCase):
    def setUp(self):
        temp_root=ROOT/"build"/"test-tmp";temp_root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=temp_root);self.sim=SimTransport();self.c=Client(self.sim,self.tmp.name)
        self.c.request(HELLO)
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def test_configuration_roundtrip(self):
        self.c.request(CONFIG,"300,2222,3333")
        s=self.c.request(STATUS)
        self.assertEqual((s["period_ms"],s["light_raw"],s["motion_raw"]),(300,2222,3333))
    def test_rejected_configuration(self):
        with self.assertRaises(ValueError):self.c.request(CONFIG,"1,2,3")
        self.assertEqual(self.c.request(STATUS)["period_ms"],200)
    def test_event_commit_ack_and_duplicate(self):
        event_id="1234567890abcdef-00000001"
        obj=dict(id=event_id,ms=1,als=5000,motion=0)
        for _ in range(2):
            with self.sim.lock:self.sim.events[event_id]=obj;self.sim._send(EVENT,1,obj)
            end=time.monotonic()+2
            while time.monotonic()<end:
                with self.sim.lock:done=event_id not in self.sim.events
                if done:break
                time.sleep(.02)
            self.assertTrue(done)
        with sqlite3.connect(Path(self.tmp.name)/"events.sqlite3") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE id=?",(event_id,)).fetchone()[0],1)
        db.close()
    def test_request_timeout(self):
        original=self.sim.write
        self.sim.write=lambda data:len(data)
        with self.assertRaises(TimeoutError):self.c.request(STATUS,timeout=.05)
        self.sim.write=original
    def test_disconnect_releases_waiter(self):
        self.sim.close();time.sleep(.1)
        self.assertFalse(self.c.running);self.assertIsNotNone(self.c.error)

if __name__=="__main__":unittest.main(verbosity=2)
