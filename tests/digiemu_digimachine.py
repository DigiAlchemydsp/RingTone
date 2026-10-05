#!/usr/bin/env python3
"""Digi Machine (Digitone mk1/Keys, OS 1.43) - emulator engage test.

OBSOLETE: this test uses a fast spin, which does NOT run the render ISR (0
visits at 0x4009d108), so it can never observe P_ON change and always FAILs.
Kept only for historical reference. Use `digiemu_digimachine_live.py` instead,
which drives the GUI worker (real 48 kHz renders) and PASSes.

Opens the settled snapshot and checks the Stage-1 pivot: the machine engages when
the selected track's SYN1 ALGORITHM is one of the added wavetable slots (>= 8).

The device pointer at 0x4138E214 is the current pattern slot; the algorithm is the
long at +0x16119 (the same word the getter at 0x4009444A reads). `dmachine_render_in`
(ev_render_in) reads it every block and writes shared P_ON (main view 0x10000800).

     python tests/digiemu_digimachine.py --fw dn1-2.3c-2cf05cb3

Needs the patched-Unicorn python (the digiemu venv).
"""
import argparse
import os
import struct
import sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)

GUI_FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)

SOUND_PTR = 0x4138E214
ALGO_OFF = 0x16119
SHARED = 0x10000000
P_ON = SHARED + 0x800          # main -> DSP
A_AUDIO = SHARED + 0x880       # DSP -> main, 32 stereo frames


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
    ap.add_argument("--step", type=lambda s: int(s, 0), default=12_000_000)
    a = ap.parse_args()
    env(a.fw)

    from emu import config, longrun, symbols
    from emu.uiresume import open_snapshot

    snap = None
    for dp, _, fs in os.walk(os.environ["DT2_SNAPSHOTS"]):
        if "gui.snap" in fs:
            snap = os.path.join(dp, "gui.snap")
    img = open(config.main_image(), "rb").read()
    prof = symbols.resolve(img, load_addr=0x40000400)
    m, ev, st, pc, inq, at, pits = open_snapshot(
        snap, os.environ["DT2_SYX"], prof, unblock_except=(prof.frame_sem,),
        **GUI_FLAGS)

    def spin(pc, n):
        pc, _e, _w = longrun.spin(m, pc, n, pits=pits)
        return pc

    def rd(addr, n=4):
        return int.from_bytes(m.peek(addr, n), "big")

    def wr(addr, val, n=4):
        m.poke(addr, val.to_bytes(n, "big"))

    pc = spin(pc, 8_000_000)

    base = rd(SOUND_PTR)
    print("sound base (*0x%08x) = 0x%08x" % (SOUND_PTR, base))
    assert base, "the current-sound pointer is null (no pattern selected?)"
    algo = rd(base + ALGO_OFF)
    print("algorithm (base+0x16119) = %d" % algo)

    # the render must be running: P_ON is written every block (0 while algo < 8)
    on0 = rd(P_ON)
    print("P_ON with algorithm=%d -> %d (expect 0)" % (algo, on0))
    ok = on0 == 0

    # select a wavetable slot: algorithm 8..15 -> dmachine_on
    wr(base + ALGO_OFF, 11)
    pc = spin(pc, a.step)
    on1 = rd(P_ON)
    print("P_ON with algorithm=11 -> %d (expect 1)" % on1)
    ok = ok and (on1 == 1)

    # the engine should be writing the 32 stereo frames in shared +0x880
    audio = bytes(m.peek(A_AUDIO, 0x100))
    vals = struct.unpack(">64i", audio)
    nz = sum(1 for v in vals if v)
    distinct = len(set(vals))
    print("machine audio: %d/%d non-zero, %d distinct (expect >0 and >1)" % (nz, len(vals), distinct))
    ok = ok and nz > 0 and distinct > 1

    # back to an FM algorithm -> machine off
    wr(base + ALGO_OFF, algo)
    pc = spin(pc, a.step)
    on2 = rd(P_ON)
    print("P_ON restored to algorithm=%d -> %d (expect 0)" % (algo, on2))
    ok = ok and (on2 == 0)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
