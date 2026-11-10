"""Create a Linux deployment tarball with executable modes preserved on Windows."""
import hashlib
import tarfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
dest=root/"release"/"serial-monitor-board.tar.gz"
paths=[root/"release/arm/monitor", *sorted((root/"scripts").glob("*.sh"))]
if not paths[0].is_file():
    raise SystemExit("Build release/arm/monitor first")
with tarfile.open(dest,"w:gz") as tar:
    for p in paths:
        info=tar.gettarinfo(str(p),"serial-monitor/"+p.relative_to(root).as_posix())
        info.mode=0o755
        info.uid=info.gid=0
        info.uname=info.gname="root"
        with p.open("rb") as stream:
            tar.addfile(info,stream)
print(dest)
print("SHA256",hashlib.sha256(dest.read_bytes()).hexdigest())
