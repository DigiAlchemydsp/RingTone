#!/usr/bin/env python3
"""Locate the stock per-track reverb send (headless, clean diffs).

T1 -> AMP -> PAGE (second sub-page), turn encoder G, and diff the sound /
render regions with the CPU stopped between reads.

    python tests/_diag_sendfind.py --fw dn1-3.2b-7e3e30a3
"""
import argparse, os, struct, sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
WIRE = {19: (3, 7), 21: (2, 3), 22: (2, 4), 23: (2, 5), 24: (2, 6), 42: (4, 6)}


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


REGIONS = [
    ("sound",  0x41300000, 0x100000),
    ("tsound", 0x419F0000, 0x10000),
    ("pat",    0x407FC000, 0x20000),
    ("vrec",   0x800034C4, 0x4F0),
    ("fxsend", 0x80005434, 0x1400),
    ("tlive",  0x800055D4, 0x400),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fw", required=True)
    ap.add_argument("--step", type=lambda s: int(s, 0), default=12_000_000)
    ap.add_argument("--out", default="sendfind_out")
    a = ap.parse_args()
    env(a.fw)
    from emu import config, longrun, panel, panelin, symbols
    from emu.uiresume import open_snapshot
    snap = [os.path.join(dp, f) for dp, _, fs in os.walk(os.environ["DT2_SNAPSHOTS"])
            for f in fs if f == "gui.snap"][0]
    img = open(config.main_image(), "rb").read()
    prof = symbols.resolve(img, load_addr=0x40000400)
    m, ev, st, pc, inq, at, pits = open_snapshot(
        snap, os.environ["DT2_SYX"], prof, unblock_except=(prof.frame_sem,), **FLAGS)
    os.makedirs(a.out, exist_ok=True)
    cap = panel.Capture(at, diff_addr=getattr(prof, "panel_diff", None),
                        front_addr=prof.fb_front)

    def shot(name):
        if cap.frames:
            panel.write_png(cap.frames[-1], os.path.join(a.out, name), scale=6)
            print("  wrote", name)

    def spin(n):
        nonlocal pc
        pc, _e, _w = longrun.spin(m, pc, n, pits=pits)

    def btn(code, down):
        nonlocal pc
        ch, bit = WIRE[code]
        pc = panelin.feed(m, prof, panelin.encode_buttons(ch, (1 << bit) if down else 0))

    def turn(ch, d):
        nonlocal pc
        pc = panelin.feed(m, prof, panelin.encode_encoder(ch, d))

    def read():
        return {name: m.peek(base, ln) for name, base, ln in REGIONS}

    def diff(r0, r1):
        out = []
        for name, base, ln in REGIONS:
            b0, b1 = r0[name], r1[name]
            for i in range(ln):
                if b0[i] != b1[i]:
                    out.append("%s+0x%05x %d->%d" % (name, i, b0[i], b1[i]))
        return out

    spin(8_000_000)
    btn(42, True); spin(4_000_000); btn(42, False); spin(6_000_000)  # T1
    btn(24, True); spin(4_000_000); btn(24, False); spin(8_000_000)  # AMP
    shot("amp1.png")
    btn(24, True); spin(4_000_000); btn(24, False); spin(8_000_000)  # AMP again -> sub-page
    shot("amp2.png")

    base = read()
    turn(6, 32); spin(a.step)                                        # encoder G (0-based ch 6)
    shot("amp2-encG.png")
    after = read()
    moved = diff(base, after)
    print("AMP page 2 enc G changed:", len(moved))
    for s in moved[:80]:
        print("   ", s)


if __name__ == "__main__":
    sys.exit(main())
