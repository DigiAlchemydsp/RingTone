#!/usr/bin/env python3
"""Digi per-pattern store (Digitone mk1): every FX param rides the saved pattern
in ONE reserved MIDI-track block -- MIDI track 4, `pattern + 0x1BB0`, magic
`"DGX4"`, packed (1-7 bits each).

The old scheme spread the params over the MIDI-track blocks at
`+0x1040/+0x1410/+0x17E0` (MIDI tracks 1-3); a configured MIDI track writes its
channel/page there, so the stock data and our values corrupted each other. The
store now uses only MIDI track 4, reserved on channel 16, so MIDI tracks 1-3
(channels 1-15) are never touched.

Checks:
  - `+0x1040/+0x1410/+0x17E0` carry no `"DGX"` magic (channels 1-3 untouched);
  - `+0x1BB0` carries `"DGX4"` and holds the packed params;
  - an edit is saved; a pattern switch isolates it and a return reloads it.

    python tests/digiemu_pattern_store.py --fw dn1-4.0a-<hash> \\
        --map /tmp/ToneFX40a.syx.map.json

The edit is simulated by writing the parameter global and the store's dirty
flag (exactly what a page encoder / CC does), so the test does not depend on
the emulator's MIDI/CC entry path. `--map` is the `.map.json` elekloader writes
next to the patched `.syx`. Needs the patched-Unicorn venv.
"""
import argparse
import json
import os
import struct
import sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)

PAT_BASE = 0x407FC414
PAT_STRIDE = 0x1611D
PTR = 0x4138E214
STORE_OFF = 0x1BB0                       # MIDI track 4 (t=7), reserved on CH 16
OLD_BLOCKS = (0x1040, 0x1410, 0x17E0)    # MIDI tracks 1-3: must stay clean
WIRE = {4: (3, 0), 26: (3, 1), 27: (4, 0)}   # PTN, trig 1 (slot 0), trig 2 (slot 1)
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)


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


def ring_depth(b):
    """param 1 (RING depth): 1 bit of RING on, then 7 bits little-endian."""
    v = 0
    for k in range(7):
        bit = 1 + k
        v |= ((b[7 + bit // 8] >> (bit % 8)) & 1) << k
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fw", required=True)
    ap.add_argument("--map", required=True, help="the patched .map.json")
    a = ap.parse_args()
    env(a.fw)

    raw = json.load(open(a.map))
    m = {k: (int(v, 16) if isinstance(v, str) else v)
         for k, v in raw.items()
         if isinstance(v, int) or (isinstance(v, str) and v.startswith("0x"))}

    from emu import config, longrun, panelin, symbols
    from emu.uiresume import open_snapshot
    snap = [os.path.join(dp, f) for dp, _, fs in os.walk(os.environ["DT2_SNAPSHOTS"])
            for f in fs if f == "gui.snap"][0]
    img = open(config.main_image(), "rb").read()
    prof = symbols.resolve(img, load_addr=0x40000400)
    mch, ev, st, pc, inq, at, pits = open_snapshot(
        snap, os.environ["DT2_SYX"], prof, unblock_except=(prof.frame_sem,), **FLAGS)

    GDEPTH = m["digiring_depth"]
    DIRTY = m["dn_store_dirty"]

    def spin(n):
        nonlocal pc
        pc, _e, _w = longrun.spin(mch, pc, n, pits=pits)

    def r32(addr):
        return int.from_bytes(bytes(mch.peek(addr, 4)), "big")

    def block(p):
        return bytes(mch.peek(p + STORE_OFF, 40))

    def set_depth(v):
        mch.poke(GDEPTH, struct.pack(">i", v))
        mch.poke(DIRTY, struct.pack(">i", 1))

    def tap(code):
        nonlocal pc
        ch, bit = WIRE[code]
        pc = panelin.feed(mch, prof, panelin.encode_buttons(ch, 1 << bit))
        spin(6_000_000)
        pc = panelin.feed(mch, prof, panelin.encode_buttons(ch, 0))
        spin(10_000_000)

    def old_clean(p):
        return all(bytes(mch.peek(p + o, 4))[0:3] != b"DGX" for o in OLD_BLOCKS)

    ok = True
    spin(8_000_000)
    p0 = r32(PTR)
    slot0 = (p0 - PAT_BASE) // PAT_STRIDE
    print("pattern ptr = 0x%08x  slot=%d" % (p0, slot0))

    # 1. the old channel-1/2/3 blocks are untouched; the CH-16 block is ours
    b0 = block(p0)
    print("  MIDI 1-3 blocks clean:", old_clean(p0))
    print("  +0x1BB0: %s  ring_depth=%d" % (b0[:4].hex(), ring_depth(b0)))
    ok = ok and old_clean(p0) and b0[0:4] == b"DGX4"

    # 2. an edit is saved into the block on the next tick
    set_depth(100)
    spin(3_000_000)
    b0 = block(p0)
    print("ring depth 100 -> global=%d block: %s ring_depth=%d"
          % (r32(GDEPTH), b0[:4].hex(), ring_depth(b0)))
    ok = ok and r32(GDEPTH) == 100 and b0[0:4] == b"DGX4" and ring_depth(b0) == 100

    # 3. switch pattern; the new slot adopts live, a distinct edit stays local
    tap(4)
    tap(27)
    p1 = r32(PTR)
    slot1 = (p1 - PAT_BASE) // PAT_STRIDE
    b1 = block(p1)
    print("after PTN+TRIG2: ptr=0x%08x slot=%d delta=0x%x block=%s"
          % (p1, slot1, p1 - p0, b1[:4].hex()))
    ok = ok and p1 == p0 + PAT_STRIDE and old_clean(p1) and b1[0:4] == b"DGX4"
    set_depth(30)
    spin(3_000_000)
    b1 = block(p1)
    print("ring depth 30 on slot %d -> global=%d block ring_depth=%d"
          % (slot1, r32(GDEPTH), ring_depth(b1)))
    ok = ok and r32(GDEPTH) == 30 and ring_depth(b1) == 30

    # 4. back to slot 0; its block must reload 100, and channels 1-3 stay clean
    tap(4)
    tap(26)
    p2 = r32(PTR)
    slot2 = (p2 - PAT_BASE) // PAT_STRIDE
    b2 = block(p2)
    spin(3_000_000)
    print("back: ptr=0x%08x slot=%d global=%d block ring_depth=%d (expect 100)"
          % (p2, slot2, r32(GDEPTH), ring_depth(b2)))
    ok = ok and p2 == p0 and slot2 == slot0 and r32(GDEPTH) == 100 and ring_depth(b2) == 100
    ok = ok and old_clean(p2)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
