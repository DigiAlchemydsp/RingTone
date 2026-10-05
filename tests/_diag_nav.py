#!/usr/bin/env python3
"""Sync navigation diagnostic (no SSI, fast): open SYN1 on T1, step ALGORITHM,
capture screenshots, read the algorithm value."""
import argparse, os, struct, sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
SOUND_PTR = 0x4138E214
ALGO_OFF = 0x16119
P_ON = 0x10000000 + 0x800

WIRE = {1: (0, 2), 12: (4, 1), 13: (3, 4), 14: (4, 2), 15: (3, 5), 16: (4, 4),
        18: (3, 6), 19: (3, 7), 21: (2, 3), 42: (4, 6), 43: (4, 7)}


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
    ap.add_argument("--out", default="out")
    ap.add_argument("--step", type=lambda s: int(s, 0), default=12_000_000)
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
        snap, os.environ["DT2_SYX"], prof, unblock_except=(prof.frame_sem,), **FLAGS)
    os.makedirs(a.out, exist_ok=True)
    cap = panel.Capture(at, diff_addr=getattr(prof, "panel_diff", None),
                        front_addr=prof.fb_front)

    def spin(n):
        nonlocal pc
        pc, _e, _w = longrun.spin(m, pc, n, pits=pits, fast=True)
        return pc

    def btn(code, down, held=0):
        nonlocal pc
        ch, bit = WIRE[code]
        pc = panelin.feed(m, prof, panelin.encode_buttons(
            ch, (held | (1 << bit)) if down else (held & ~(1 << bit))))

    def tap(code, n=None):
        btn(code, True); spin(n or a.step)
        btn(code, False); spin(n or a.step)

    def shot(name):
        if cap.frames:
            panel.write_png(cap.frames[-1], os.path.join(a.out, name), scale=6)
            print("  wrote", name, "(%d frames)" % len(cap.frames))
        else:
            print("  NO FRAMES for", name)

    def rd(addr, n=4):
        return int.from_bytes(m.peek(addr, n), "big")

    spin(8_000_000)
    base = rd(SOUND_PTR)
    print("start: base=0x%08x algo=%d P_ON=%d frames=%d"
          % (base, rd(base + ALGO_OFF) if base else -1, rd(P_ON), len(cap.frames)))
    shot("00-start.png")

    tap(12)   # STOP
    shot("01-stop.png")
    tap(42)   # T1
    shot("02-t1.png")
    print("after T1: base=0x%08x" % rd(SOUND_PTR))
    tap(21)   # SYN1
    shot("03-syn1.png")
    base = rd(SOUND_PTR)
    print("after SYN1: base=0x%08x algo=%d" % (base, rd(base + ALGO_OFF)))

    tap(19)   # PAGE: algorithm diagram sub-page (1/2)
    shot("03b-page.png")

    for i in range(20):
        pc = panelin.feed(m, prof, panelin.encode_encoder(1, 16))
        spin(4_000_000)
        base = rd(SOUND_PTR)
        if i % 5 == 0 or rd(base + ALGO_OFF) >= 8:
            print("  step %d: base=0x%08x algo=%d P_ON=%d"
                  % (i, base, rd(base + ALGO_OFF), rd(P_ON)))
    shot("04-algo-stepped.png")
    base = rd(SOUND_PTR)
    print("final: base=0x%08x algo=%d P_ON=%d" % (base, rd(base + ALGO_OFF), rd(P_ON)))


if __name__ == "__main__":
    sys.exit(main())
