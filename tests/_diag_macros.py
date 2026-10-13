#!/usr/bin/env python3
"""Screenshot every macro page (kinds 7..10) off and on (amount raised)."""
import argparse, os, struct, sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
VT_MASTER = 0x40199BAC
WIRE = {1: (0, 2), 25: (2, 7)}
NAMES = {7: "wash", 8: "radio", 9: "destroy", 10: "space"}


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
    ap.add_argument("--out", default="macro_out")
    ap.add_argument("--step", type=lambda s: int(s, 0), default=10_000_000)
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

    def spin(n):
        nonlocal pc
        pc, _e, _w = longrun.spin(m, pc, n, pits=pits)

    def btn(code, down):
        nonlocal pc
        ch, bit = WIRE[code]
        pc = panelin.feed(m, prof, panelin.encode_buttons(ch, (1 << bit) if down else 0))

    def enc(ch, d):
        nonlocal pc
        pc = panelin.feed(m, prof, panelin.encode_encoder(ch, d))

    def rd(addr):
        return int.from_bytes(m.peek(addr, 4), "big")

    def shot(name):
        if cap.frames:
            panel.write_png(cap.frames[-1], os.path.join(a.out, name), scale=6)
            print("  wrote", name)

    spin(8_000_000)
    btn(1, True); spin(a.step)
    btn(25, True); spin(a.step)
    btn(25, False); spin(a.step)
    btn(1, False); spin(a.step)
    view = None
    for base in range(0x40000000, 0x44000000, 0x100000):
        data = m.peek(base, 0x100000)
        off = data.find(struct.pack('>I', VT_MASTER))
        if off >= 0 and base + off >= 0x41000000:
            view = base + off
            break
    vec = rd(view + 124)
    n = (rd(view + 128) - vec) // 4
    kinds = [rd(vec + 4 * i) for i in range(n)]
    print("kinds:", kinds)
    for k in sorted(NAMES):
        assert k in kinds, "kind %d missing" % k
        m.poke(view + 144, kinds.index(k).to_bytes(4, "big"))
        spin(a.step)
        shot("%d-%s-off.png" % (k, NAMES[k]))
        enc(0, 16); spin(a.step)                 # A -> on
        enc(1, 63); enc(1, 63); spin(a.step)     # B x2 -> amount up
        shot("%d-%s-on.png" % (k, NAMES[k]))
        enc(0, -16); spin(a.step)                # A -> off


if __name__ == "__main__":
    sys.exit(main())
