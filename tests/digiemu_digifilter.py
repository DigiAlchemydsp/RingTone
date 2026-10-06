#!/usr/bin/env python3
"""Digi Filter (Digitone mk1/Keys, OS 1.43) - emulator UI test.

Opens the settled snapshot, opens the master page tree (FUNC+LFO), asserts that
the DIGI FILTER page (kind 1) is in the page-kind vector next to DIGI FX
(kind 0), selects it, and captures screenshots while toggling a voice and
stepping the mode. Run against a firmware built with core-dn1 + digifilter +
digictl 1.3 (+ the other DIGI FX mods).

    python tests/digiemu_digifilter.py --fw dn1-2.0p-64ae075a

Needs the patched-Unicorn python (the digiemu venv).
"""
import argparse
import os
import struct
import sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)

# measured Digitone panel wire map (devices/digitone.toml [panel.exceptions])
WIRE = {1: (0, 2), 17: (4, 3), 18: (3, 6), 25: (2, 7), 26: (3, 1),
        42: (4, 6), 43: (4, 7), 44: (6, 6), 45: (6, 7)}
GUI_FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
VT_MASTER = 0x40199BAC


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


def find_views(m):
    """All objects whose vtable pointer is the master view's."""
    for base in range(0x40000000, 0x44000000, 0x100000):
        try:
            data = m.peek(base, 0x100000)
        except Exception:
            continue
        off = data.find(struct.pack('>I', VT_MASTER))
        while off >= 0:
            if base + off >= 0x41000000:
                yield base + off
            off = data.find(struct.pack('>I', VT_MASTER), off + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fw", required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--step", type=lambda s: int(s, 0), default=18_000_000)
    a = ap.parse_args()
    env(a.fw)

    from emu import config, longrun, panel, panelin, symbols
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
    os.makedirs(a.out, exist_ok=True)
    cap = panel.Capture(at, diff_addr=getattr(prof, "panel_diff", None),
                        front_addr=prof.fb_front)

    def spin(pc, n):
        pc, _e, _w = longrun.spin(m, pc, n, pits=pits)
        return pc

    def btn(code, down):
        ch, bit = WIRE[code]
        return panelin.feed(m, prof,
                            panelin.encode_buttons(ch, (1 << bit) if down else 0))

    def shot(name):
        if cap.frames:
            panel.write_png(cap.frames[-1], os.path.join(a.out, name), scale=6)
            print("  wrote", name)

    pc = spin(pc, 8_000_000)

    # FUNC+LFO opens the master page tree.
    pc = btn(1, True); pc = spin(pc, a.step)
    pc = btn(25, True); pc = spin(pc, a.step)
    pc = btn(25, False); pc = spin(pc, a.step)
    pc = btn(1, False); pc = spin(pc, a.step)
    shot("00-intro.png")

    views = list(find_views(m))
    print("master views:", [hex(v) for v in views])
    assert views, "master view not found (did the page open?)"
    found = False
    for view in views:
        vec = struct.unpack('>I', m.peek(view + 124, 4))[0]
        n = (struct.unpack('>I', m.peek(view + 128, 4))[0] - vec) // 4
        kinds = [struct.unpack('>I', m.peek(vec + 4 * i, 4))[0] for i in range(min(n, 12))]
        print("view %s kinds=%s" % (hex(view), kinds))
        if 0 in kinds and 1 in kinds:
            found = True
            # select DIGI FX (kind 0), then RIGHT switches to DIGI FILTER (kind 1)
            m.poke(view + 144, kinds.index(0).to_bytes(4, "big"))
            pc = spin(pc, a.step)
            shot("00b-digi-fx.png")
            pc = btn(18, True); pc = spin(pc, 4_000_000)
            pc = btn(18, False); pc = spin(pc, a.step)
            idx = struct.unpack('>I', m.peek(view + 144, 4))[0]
            assert idx == kinds.index(1), "RIGHT did not switch to DIGI FILTER (idx=%d)" % idx
            shot("01-filter-page.png")
            # mode: encoder B (channel 1), one step = one detent = 4 counts
            pc = panelin.feed(m, prof, panelin.encode_encoder(1, 4))
            pc = spin(pc, a.step)
            shot("02-mode-next.png")
            # toggle voice 1 off
            pc = btn(26, True); pc = spin(pc, 4_000_000)
            pc = btn(26, False); pc = spin(pc, a.step)
            shot("03-voice1-off.png")
            # freq up one step
            pc = panelin.feed(m, prof, panelin.encode_encoder(2, 4))
            pc = spin(pc, a.step)
            shot("04-freq-up.png")
            break
    assert found, "DIGI FILTER page (kind 1) not found in the master view"
    print("PASS: DIGI FILTER page present and selectable")


if __name__ == "__main__":
    main()
