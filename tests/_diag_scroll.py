#!/usr/bin/env python3
"""Decisive: feed encoder A negative (as the operator did), re-read SOUND_PTR
each step, and diff the whole sound region to find where the algorithm lands."""
import argparse, os, struct, sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
SOUND_PTR = 0x4138E214
ALGO_OFF = 0x16119
P_ON = 0x10000000 + 0x800

WIRE = {1: (0, 2), 12: (4, 1), 19: (3, 7), 21: (2, 3), 42: (4, 6)}


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
    ap.add_argument("--scan", action="store_true")
    a = ap.parse_args()
    env(a.fw)
    from emu import config, longrun, panelin, symbols
    from emu.uiresume import open_snapshot

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

    def rd(addr, n=4):
        return int.from_bytes(m.peek(addr, n), "big")

    spin(6_000_000)
    base = rd(SOUND_PTR)
    print("base=0x%08x *base=0x%08x" % (base, rd(base)))
    region = 0x4000      # covers 0..0x1612d plus headroom
    before = bytes(m.peek(base, region))

    # one big negative scroll (matches the operator's encoder A)
    for _ in range(8):
        pc = panelin.feed(m, prof, panelin.encode_encoder(1, -16))
        spin(4_000_000)
    after = bytes(m.peek(rd(SOUND_PTR), region))
    base_after = rd(SOUND_PTR)
    print("after scroll: SOUND_PTR=0x%08x algo_at_old_off=%d"
          % (base_after, rd(base_after + ALGO_OFF)))

    diffs = [i for i in range(0, region, 2) if before[i:i+2] != after[i:i+2]]
    print("2-byte diffs vs before:", [hex(i) for i in diffs][:100])
    for i in diffs[:60]:
        print("  +0x%05x: %s -> %s" % (i, before[i:i+2].hex(), after[i:i+2].hex()))

    if a.scan:
        # try each encoder channel in turn, reporting the diff offsets
        for ch in range(4):
            b0 = bytes(m.peek(rd(SOUND_PTR), region))
            pc = panelin.feed(m, prof, panelin.encode_encoder(ch + 1, -16))
            spin(4_000_000)
            b1 = bytes(m.peek(rd(SOUND_PTR), region))
            d = [hex(i) for i in range(0, region, 2) if b0[i:i+2] != b1[i:i+2]]
            print("encoder %d ccw diffs: %s" % (ch, d[:20]))


if __name__ == "__main__":
    sys.exit(main())
