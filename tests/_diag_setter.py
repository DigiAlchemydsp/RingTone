#!/usr/bin/env python3
"""Hook the algorithm setter 0x40025e30 while feeding encoder A; record the
param id ($8(a7)), value ($10(a7)), and what 0x40025c56 resolves it to."""
import argparse, os, struct, sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
SOUND_PTR = 0x4138E214
ALGO_OFF = 0x16119
P_ON = 0x10000000 + 0x800


def env(fw):
    fwdir = os.path.join(DIGIEMU, "portable", "firmware", fw)
    syx = [f for f in os.listdir(fwdir) if f.endswith(".syx")][0]
    os.environ.update({
        "DT2_SYX": os.path.join(fwdir, syx), "DT2_SECTIONS": fwdir + "/sections",
        "DT2_SNAPSHOTS": fwdir + "/snapshots", "DT2_PLUSDRIVE": fwdir + "/plusdrive.img",
        "DT2_MAIN_IMG": fwdir + "/sections/section_3_MAIN_OS.bin",
        "DT2_DEVICES": fwdir + "/devices" if os.path.isdir(fwdir + "/devices")
        else os.path.join(DIGIEMU, "devices")})
    os.chdir(fwdir)
    return fwdir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fw", required=True)
    ap.add_argument("--step", type=lambda s: int(s, 0), default=8_000_000)
    a = ap.parse_args()
    env(a.fw)
    from emu import config, longrun, panelin, symbols
    from emu.uiresume import open_snapshot
    from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_D0, UC_M68K_REG_PC

    snap = None
    for dp, _, fs in os.walk(os.environ["DT2_SNAPSHOTS"]):
        if "gui.snap" in fs:
            snap = os.path.join(dp, "gui.snap")
    img = open(config.main_image(), "rb").read()
    prof = symbols.resolve(img, load_addr=0x40000400)
    m, ev, st, pc, inq, at, pits = open_snapshot(
        snap, os.environ["DT2_SYX"], prof, unblock_except=(prof.frame_sem,), **FLAGS)

    def spin(n):
        nonlocal pc
        pc, _e, _w = longrun.spin(m, pc, n, pits=pits, fast=True)

    log = []

    def setter_hook(uc, addr, size, data):
        a7 = uc.reg_read(UC_M68K_REG_A7)
        pid = struct.unpack(">i", uc.mem_read(a7 + 8, 4))[0]
        val = struct.unpack(">i", uc.mem_read(a7 + 0x10, 4))[0]
        d0 = uc.reg_read(UC_M68K_REG_D0)
        log.append(("setter", pid, val, d0, addr))

    at(0x40025E30, setter_hook)

    def resolver_hook(uc, addr, size, data):
        a7 = uc.reg_read(UC_M68K_REG_A7)
        pid = struct.unpack(">i", uc.mem_read(a7 + 4, 4))[0]
        d0 = uc.reg_read(UC_M68K_REG_D0)
        log.append(("resolver", pid, d0, addr))

    at(0x40025C56, resolver_hook)

    spin(6_000_000)
    base = int.from_bytes(m.peek(SOUND_PTR, 4), "big")
    print("base=0x%08x algo=%d P_ON=%d"
          % (base, int.from_bytes(m.peek(base + ALGO_OFF, 4), "big"),
             int.from_bytes(m.peek(P_ON, 4), "big")))

    for label, ch, delta in (("A ccw", 0, -16), ("A cw", 0, 16),
                             ("B ccw", 1, -16), ("B cw", 1, 16)):
        log.clear()
        pc = panelin.feed(m, prof, panelin.encode_encoder(ch + 1, delta))
        spin(a.step)
        base = int.from_bytes(m.peek(SOUND_PTR, 4), "big")
        algo = int.from_bytes(m.peek(base + ALGO_OFF, 4), "big")
        on = int.from_bytes(m.peek(P_ON, 4), "big")
        print("\n== %s (ch %d, delta %d): algo=%d P_ON=%d ==" % (label, ch, delta, algo, on))
        for e in log[:20]:
            print("   ", e)


if __name__ == "__main__":
    sys.exit(main())
