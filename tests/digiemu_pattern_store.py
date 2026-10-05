#!/usr/bin/env python3
"""Digi store: the DIGI FX params are kept in the saved pattern structure.

`digictl` 1.4 writes its 17 parameters into a 64-byte block at
`pattern + 0x1040`, where the current pattern is `*(0x4138E214)` and the project
patterns are `0x407FC414 + slot*0x1611D`. This checks, on a firmware the app
built from `core-dn1` + the suite mods:

  - the current pattern's block carries the "DGX1" magic and the mod defaults;
  - the OS does not clobber the block while it runs;
  - switching to another pattern selects a different block (per-pattern state).

    python tests/digiemu_pattern_store.py --fw dn1-2.1z-d2535be9

Needs the patched-Unicorn venv (see the other digiemu tests).
"""
import argparse
import os
import struct
import sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)

SOUND_PTR = 0x4138E214
PAT_BASE = 0x407FC414
PAT_STRIDE = 0x1611D
BLK = 0x1040
N = 17
WIRE = {4: (3, 0), 27: (4, 0)}          # PTN, trig 2
GUI_FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)


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
    a = ap.parse_args()
    env(a.fw)

    from emu import config, longrun, panelin, symbols
    from emu.uiresume import open_snapshot
    snap = [os.path.join(dp, f) for dp, _, fs in os.walk(os.environ["DT2_SNAPSHOTS"])
            for f in fs if f == "gui.snap"][0]
    img = open(config.main_image(), "rb").read()
    prof = symbols.resolve(img, load_addr=0x40000400)
    m, ev, st, pc, inq, at, pits = open_snapshot(
        snap, os.environ["DT2_SYX"], prof, unblock_except=(prof.frame_sem,), **GUI_FLAGS)

    def spin(n):
        nonlocal pc
        pc, _e, _w = longrun.spin(m, pc, n, pits=pits)

    def rd(addr, n=4):
        return int.from_bytes(bytes(m.peek(addr, n)), "big")

    def block(base):
        b = bytes(m.peek(base + BLK, 8 + 2 * N))
        return b[0:4], b[4:6], struct.unpack(">%dh" % N, b[8:8 + 2 * N])

    def tap(code):
        nonlocal pc
        ch, bit = WIRE[code]
        pc = panelin.feed(m, prof, panelin.encode_buttons(ch, 1 << bit))
        spin(6_000_000)
        pc = panelin.feed(m, prof, panelin.encode_buttons(ch, 0))
        spin(10_000_000)

    ok = True
    spin(8_000_000)
    b0 = rd(SOUND_PTR)
    mag, ver, vals = block(b0)
    print("pattern 0x%08x magic=%r ver=%s depth=%d eqlo=%d filter=%d"
          % (b0, mag, ver.hex(), vals[1], vals[5], vals[10]))
    ok = ok and mag == b"DGX1" and vals[1] == 51 and vals[5] == 33

    # the OS must leave the block alone (marker survives a busy run)
    bb = bytearray(m.peek(b0 + BLK, 8 + 2 * N))
    struct.pack_into(">h", bb, 8 + 2 * 8, 777)      # fold amount
    m.poke(b0 + BLK, bytes(bb))
    spin(30_000_000)
    kept = block(b0)[2][8] == 777
    print("marker survived run:", kept)
    ok = ok and kept

    # per pattern: PTN + trig 2 -> a different block
    tap(4)
    tap(27)
    b1 = rd(SOUND_PTR)
    mag1 = block(b1)[0]
    print("after PTN+TRIG2: base=0x%08x (delta 0x%x) magic=%r"
          % (b1, b1 - b0, mag1))
    ok = ok and b1 == b0 + PAT_STRIDE and mag1 == b"DGX1"

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
