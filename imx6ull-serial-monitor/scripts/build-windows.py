"""Reproducible Windows cross-build using Zig's Clang/LLD and the supplied Linaro sysroot.
No install, PATH changes, or Linux VM required. The full Linux GCC is NOT executable on Win11.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tarfile

p=argparse.ArgumentParser()
p.add_argument("--zig",required=True,help="zig.exe 0.13.0")
p.add_argument("--linaro",required=True,help="gcc-linaro-4.9.4-2017.01-x86_64_arm-linux-gnueabihf.tar.xz")
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
build=root/"build";build.mkdir(exist_ok=True)
tmp=build/"tmp";tmp.mkdir(exist_ok=True)
os.environ["TEMP"]=str(tmp);os.environ["TMP"]=str(tmp)
zig=Path(a.zig).resolve();zlib=zig.parent/"lib"
sysroot=build/"linaro"
marker=sysroot/".complete"
if not marker.exists():
    with tarfile.open(a.linaro) as tar:
        for member in tar:
            rel=Path(*Path(member.name).parts[1:])
            if str(rel).replace("\\","/").startswith(("arm-linux-gnueabihf/libc/", "lib/gcc/arm-linux-gnueabihf/4.9.4/")):
                if member.isfile() or member.issym() or member.islnk():
                    out=(sysroot/rel).resolve()
                    if not out.is_relative_to(sysroot.resolve()):raise ValueError("unsafe archive path")
                    out.parent.mkdir(parents=True,exist_ok=True)
                    stream=tar.extractfile(member)
                    if stream:out.write_bytes(stream.read())
    marker.write_text("Linaro 4.9.4 sysroot extracted\n")

def run(*args):
    subprocess.run([str(zig),*map(str,args)],cwd=root,check=True)

libc=sysroot/"arm-linux-gnueabihf/libc"
gcc=sysroot/"lib/gcc/arm-linux-gnueabihf/4.9.4"
objects=[]
for src in ["board/src/main.c","board/src/serial.c","board/src/sensors.c","board/src/storage.c","board/src/config.c","common/protocol.c"]:
    obj=build/(Path(src).stem+"-arm.o");objects.append(obj)
    run("clang","--target=arm-linux-gnueabihf","-mcpu=cortex-a7","-mfpu=neon-vfpv4","-mfloat-abi=hard",
        "--sysroot="+str(libc),"-isystem",zlib/"include","-std=c11","-O2","-g","-fno-pie","-fno-stack-protector",
        "-Wall","-Wextra","-Werror","-pthread","-Iboard/include","-Icommon","-c",src,"-o",obj)
out=root/"release/arm/monitor";out.parent.mkdir(parents=True,exist_ok=True)
run("ld.lld","-m","armelf_linux_eabi","-static","-o",out,libc/"usr/lib/crt1.o",libc/"usr/lib/crti.o",
    gcc/"crtbeginT.o",*objects,"-L"+str(libc/"usr/lib"),"-L"+str(gcc),
    "--start-group","-lpthread","-lc","-lgcc","-lgcc_eh","--end-group",gcc/"crtend.o",libc/"usr/lib/crtn.o")

# Native DLL for testing the EXACT C parser/config code from Python ctypes.
native=[]
for src in ["common/protocol.c","board/src/config.c"]:
    obj=build/(Path(src).stem+"-win.o");native.append(obj)
    run("clang","--target=x86_64-windows-gnu","-isystem",zlib/"include","-isystem",zlib/"libc/include/any-windows-any",
        "-O2","-fno-stack-protector","-Wall","-Wextra","-Werror","-Iboard/include","-c",src,"-o",obj)
deffile=build/"msvcrt.def"
deffile.write_text("LIBRARY msvcrt.dll\nEXPORTS\nmemcpy\nmemmove\nstrtoul\n_errno\n",encoding="ascii")
run("dlltool","-m","i386:x86-64","-d",deffile,"-l",build/"msvcrt.lib")
run("lld-link","/dll","/noentry","/nodefaultlib","/machine:x64","/out:"+str(build/"mon_core.dll"),
    "/export:mon_crc","/export:mon_encode","/export:mon_feed","/export:mon_expire","/export:config_parse",
    *native,build/"msvcrt.lib")
print("Built ARM executable:",out)
print("Built native test DLL:",build/"mon_core.dll")
