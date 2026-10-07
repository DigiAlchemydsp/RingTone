#!/usr/bin/env python3
"""Digi FX MIDI CC hook (Digitone mk1, OS 1.43) - direct-invocation test.

digiemu cannot inject MIDI, so this calls the patched stock CC-router entry
(0x400ED94E, now `jsr digictl_cc_disp`) with a crafted stack - track=9 makes the
stock router return early, so only the mod's code runs - and checks that each CC
number moves the matching DIGI parameter. Also checks the change sets the
pattern-store dirty flag (`dn_store_dirty`).

    python tests/digiemu_midi_cc.py --fw dn1-2.2f-6911f75d --map ToneFX-cc.syx.map.json

`--map` is the `.map.json` elekloader writes next to the patched `.syx` (it has
the linked symbol addresses). Needs the patched-Unicorn venv.
"""
import argparse
import json
import os
import struct
import sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)

SITE = 0x400ED94E              # stock central CC router (patched by digictl 1.9)
RET = 0x40094448               # an `rts` in the main OS (our call returns here)
SCRATCH = 0x80007000           # free SRAM scratch stack
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
# (cc, value, global symbol, expected)
CASES = [
    (8, 100, "digiring_depth", 100),
    (11, 127, "digiring_on", 1),
    (11, 0, "digiring_on", 0),
    (36, 42, "digiring_freq", 42),
    (40, 64, "digifold_amount", 64),
    (41, 80, "digifold_mode", 80),
    (67, 127, "digieq_on", 1),
    (67, 0, "digieq_on", 0),
    (69, 12, "digieq_lo", 12),
    (96, 99, "digieq_hi", 99),
    (68, 127, "digimeter_on", 1),
    (68, 0, "digimeter_on", 0),
]


def env(fw):
    d = os.path.join(DIGIEMU, "portable", "firmware", fw)
    syx = [f for f in os.listdir(d) if f.endswith(".syx")][0]
    os.environ.update({
        "DT2_SYX": os.path.join(d, syx), "DT2_SECTIONS": d + "/sections",
        "DT2_SNAPSHOTS": d + "/snapshots", "DT2_PLUSDRIVE": d + "/plusdrive.img",
        "DT2_MAIN_IMG": d + "/sections/section_3_MAIN_OS.bin",
        "DT2_DEVICES": d + "/devices" if os.path.isdir(d + "/devices")
        else os.path.join(DIGIEMU, "devices")})
    os.chdir(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fw", required=True)
    ap.add_argument("--map", required=True, help="the patched .map.json")
    a = ap.parse_args()
    env(a.fw)

    raw = json.load(open(a.map))
    def num(v):
        return int(v, 16) if isinstance(v, str) else v
    m = {k: num(v) for k, v in raw.items()
         if isinstance(v, int) or (isinstance(v, str) and v.startswith("0x"))}

    from emu import config, longrun, symbols
    from unicorn.m68k_const import UC_M68K_REG_A7, UC_M68K_REG_PC
    from emu.uiresume import open_snapshot
    snap = [os.path.join(dp, f) for dp, _, fs in os.walk(os.environ["DT2_SNAPSHOTS"])
            for f in fs if f == "gui.snap"][0]
    img = open(config.main_image(), "rb").read()
    prof = symbols.resolve(img, load_addr=0x40000400)
    mch, ev, st, pc, inq, at, pits = open_snapshot(
        snap, os.environ["DT2_SYX"], prof, unblock_except=(prof.frame_sem,), **FLAGS)

    def spin(n):
        nonlocal pc
        pc, _e, _w = longrun.spin(mch, pc, n, pits=pits)

    def rd(addr):
        return int.from_bytes(bytes(mch.peek(addr, 4)), "big")

    spin(8_000_000)

    disp = m["digictl_cc_disp"]
    site = bytes(mch.peek(SITE, 6))
    # the site is a `jmp` (not jsr): the glue expects the stock entry layout
    # (sp@4=track, sp@8=cc, sp@12=value) with no return address pushed.
    want = bytes([0x4E, 0xF9]) + struct.pack(">I", disp)
    print("site @%#x = %s  (want %s)" % (SITE, site.hex(), want.hex()))
    ok = site == want

    uc = mch.uc

    def call_cc(cc, value, track=9):
        # enter the real router site with the caller's frame
        mch.poke(SCRATCH, struct.pack(">IIII", RET, track, cc, value))
        saved_pc = uc.reg_read(UC_M68K_REG_PC)
        saved_sp = uc.reg_read(UC_M68K_REG_A7)
        uc.reg_write(UC_M68K_REG_A7, SCRATCH)
        uc.emu_start(SITE, RET, 0, 200000)
        uc.reg_write(UC_M68K_REG_PC, saved_pc)
        uc.reg_write(UC_M68K_REG_A7, saved_sp)

    for cc, val, name, expect in CASES:
        call_cc(cc, val)
        got = rd(m[name])
        print("CC %3d = %3d -> %-16s = %d (expect %d) %s"
              % (cc, val, name, got, expect, "OK" if got == expect else "FAIL"))
        ok = ok and got == expect
    dirty = rd(m["dn_store_dirty"])
    print("dn_store_dirty =", dirty)
    ok = ok and dirty == 1
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
