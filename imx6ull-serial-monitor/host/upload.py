"""Upload through an ALREADY LOGGED IN board shell with acknowledged blocks.
V2 uses a foreground byte-counted receiver, not a large interactive heredoc.
"""
import argparse
import base64
import hashlib
from pathlib import Path
import re
import secrets
import shlex
import time
from transport import open_serial

class BoardError(RuntimeError):
    pass

class Replies:
    def __init__(self, port, tag, log):
        self.port, self.tag, self.log = port, tag, log
        self.pending = bytearray()
        self.tail = bytearray()

    def wait(self, expected, timeout):
        end = time.monotonic() + timeout
        while True:
            while b"\n" in self.pending:
                line, _, rest = self.pending.partition(b"\n")
                self.pending = bytearray(rest)
                line = line.strip(b"\r \t")
                if line.startswith((self.tag + "_FAIL_").encode()):
                    raise BoardError("Board reported: " + line.decode("ascii", "replace") + self.details())
                if line == expected.encode():
                    return
            if time.monotonic() >= end:
                raise TimeoutError("No complete board acknowledgement: " + expected + self.details())
            chunk = self.port.read(1024)
            if chunk:
                self.log.write(chunk)
                self.log.flush()
                self.pending.extend(chunk)
                self.tail.extend(chunk)
                if len(self.tail) > 8192:
                    del self.tail[:-8192]
                if len(self.pending) > 16384:
                    del self.pending[:-8192]

    def details(self):
        return "\nLast board output:\n" + self.tail.decode("utf-8", "replace")

def send(port, data):
    if isinstance(data, str):
        data = data.encode("ascii")
    if port.write(data) != len(data):
        raise OSError("partial serial write; transfer cancelled")

def receiver_command(tag, size, block_size, digest):
    if not re.fullmatch(r"MON_[0-9a-f]{16}", tag):
        raise ValueError("invalid marker")
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or size < 1 or not 256 <= block_size <= 4096:
        raise ValueError("invalid transfer parameters")
    script = f'''
saved=$(stty -g) || exit 1;
trap 'stty "$saved"' EXIT;
trap 'exit 130' HUP INT TERM;
fail() {{ printf '\\n{tag}_FAIL_%s\\n' "$1"; exit 1; }};
for tool in dd wc cat base64 sha256sum mv; do command -v "$tool" >/dev/null 2>&1 || fail "TOOL_$tool"; done;
stty -echo -icanon isig -ixon -ixoff min 1 time 0 || fail STTY;
: > /tmp/serial-monitor-upload.b64 || fail CREATE;
printf '\\n{tag}_READY\\n';
left={size}; idx=0;
while [ "$left" -gt 0 ]; do
want={block_size}; [ "$left" -ge "$want" ] || want=$left;
dd bs=1 count="$want" of=/tmp/serial-monitor-upload.block 2>/tmp/serial-monitor-upload.err || fail READ;
got=$(wc -c < /tmp/serial-monitor-upload.block);
[ "$got" -eq "$want" ] || fail SHORT_READ;
cat /tmp/serial-monitor-upload.block >> /tmp/serial-monitor-upload.b64 || fail APPEND;
printf '\\n{tag}_ACK_%s\\n' "$idx";
left=$((left-want)); idx=$((idx+1));
done;
base64 -d /tmp/serial-monitor-upload.b64 > /tmp/serial-monitor-board.tar.gz.part || fail DECODE;
actual=$(sha256sum /tmp/serial-monitor-board.tar.gz.part) || fail HASH_TOOL;
printf '\\n%s\\n' "$actual";
set -- $actual;
[ "$1" = '{digest}' ] || fail SHA256;
mv /tmp/serial-monitor-board.tar.gz.part /tmp/serial-monitor-board.tar.gz || fail RENAME;
printf '\\n{tag}_OK\\n';
'''
    command = "sh -c " + shlex.quote(" ".join(line.strip() for line in script.splitlines() if line.strip())) + "\n"
    if len(command) >= 3500:
        raise ValueError("receiver command too long")
    return command

def upload(port, payload, tag, block_size, log, block_timeout=15, final_timeout=60):
    if not payload or len(payload) > 8*1024*1024:
        raise ValueError("archive must be between 1 byte and 8 MiB")
    digest = hashlib.sha256(payload).hexdigest()
    encoded = base64.b64encode(payload)
    replies = Replies(port, tag, log)
    send(port, receiver_command(tag, len(encoded), block_size, digest))
    replies.wait(tag + "_READY", block_timeout)
    for idx, off in enumerate(range(0, len(encoded), block_size)):
        block = encoded[off:off+block_size]
        send(port, block)
        replies.wait(f"{tag}_ACK_{idx}", block_timeout)
        if idx % 16 == 0 or off+len(block) == len(encoded):
            print(f"Board acknowledged {off+len(block)}/{len(encoded)} base64 bytes", flush=True)
    replies.wait(tag + "_OK", final_timeout)
    return digest

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True)
    p.add_argument("--file", default=str(Path(__file__).resolve().parents[1]/"release/serial-monitor-board.tar.gz"))
    p.add_argument("--block-size", type=int, default=1024, choices=(256, 512, 1024, 2048, 4096))
    a = p.parse_args()
    payload = Path(a.file).read_bytes()
    if not payload or len(payload)>8*1024*1024:
        p.error("archive must be between 1 byte and 8 MiB")
    tag = "MON_" + secrets.token_hex(8)
    log_path = Path(__file__).resolve().parents[1]/"logs"/("upload-"+tag+".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print("Upload v2: per-block board acknowledgements. Board must already be at a Linux shell.")
    print("Board output log:", log_path)
    port = open_serial(a.port)
    port.write_timeout = 2.0
    try:
        with log_path.open("wb") as log:
            digest = upload(port, payload, tag, a.block_size, log)
        print("Upload SHA256 verified:", digest)
        print("Reopen the terminal and run:")
        print("cd /tmp && tar xzf serial-monitor-board.tar.gz")
        print("sh /tmp/serial-monitor/scripts/install-board.sh")
    except (Exception, KeyboardInterrupt):
        try:
            send(port, b"\x03")
            time.sleep(.3)
        except Exception:
            pass
        print("Transfer cancelled. Do not install unless SHA256 matches the PC archive.")
        print("Reopen terminal; if needed press Ctrl+C and Enter, then run stty sane.")
        raise
    finally:
        port.close()

if __name__ == "__main__":
    main()
