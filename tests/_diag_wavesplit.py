#!/usr/bin/env python3
"""Check digiwave PITCH on/off (digiwave_on) and STEREO on/off (digiwave_son)
are independent: the PITCH page A sets one, the STEREO page A the other."""
import argparse, json, os, struct, sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
VT_MASTER = 0x40199BAC
WIRE = {1: (0, 2), 25: (2, 7)}


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
    ap.add_argument("--step", type=lambda s: int(s, 0), default=12_000_000)
    a = ap.parse_args()
    env(a.fw)
    from emu import config, longrun, panelin, symbols
    from emu.uiresume import open_snapshot
    snap = [os.path.join(dp, f) for dp, _, fs in os.walk(os.environ["DT2_SNAPSHOTS"])
            for f in fs if f == "gui.snap"][0]
    img = open(config.main_image(), "rb").read()
    prof = symbols.resolve(img, load_addr=0x40000400)
    m, ev, st, pc, inq, at, pits = open_snapshot(
        snap, os.environ["DT2_SYX"], prof, unblock_except=(prof.frame_sem,), **FLAGS)
    sym = json.load(open(os.path.join(os.path.dirname(__file__), "..", "testout",
                                      "test-3.5d.syx.map.json")))
    ON = int(sym["digiwave_on"], 16)
    SON = int(sym["digiwave_son"], 16)

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

    def show(tag):
        print("%-16s on(PITCH)=%d son(STEREO)=%d" % (tag, rd(ON), rd(SON)))

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
    kinds = [rd(vec + 4 * i) for i in range((rd(view + 128) - vec) // 4)]
    print("kinds:", kinds)
    show("start")
    m.poke(view + 144, kinds.index(4).to_bytes(4, "big")); spin(a.step)   # PITCH
    enc(0, 16); spin(a.step)
    show("PITCH A up")
    assert rd(ON) == 1 and rd(SON) == 0, "PITCH on/off leaked into STEREO"
    m.poke(view + 144, kinds.index(5).to_bytes(4, "big")); spin(a.step)   # STEREO
    enc(0, 16); spin(a.step)
    show("STEREO A up")
    assert rd(ON) == 1 and rd(SON) == 1, "STEREO on/off wrong"
    enc(0, -16); spin(a.step)
    show("STEREO A down")
    assert rd(ON) == 1 and rd(SON) == 0, "turning off STEREO killed PITCH"
    print("PASS")


if __name__ == "__main__":
    sys.exit(main())
