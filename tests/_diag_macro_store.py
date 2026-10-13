#!/usr/bin/env python3
"""RADIO/DESTROY/SPACE persist per pattern in the second store block
(pattern+0x1410, magic "DGX2")."""
import argparse, json, os, struct, sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
VT_MASTER = 0x40199BAC
PAT_PTR = 0x4138E214
STORE2 = 0x1410
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
    AMT = int(sym["dgmac2_amount"], 16)

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

    def rd(addr, n=4):
        return int.from_bytes(m.peek(addr, n), "big")

    def blk2_amt():
        b = rd(PAT_PTR) + STORE2
        return m.peek(b, 4), int.from_bytes(m.peek(b + 10, 2), "big")

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
    m.poke(view + 144, kinds.index(8).to_bytes(4, "big")); spin(a.step)   # RADIO
    enc(1, 63); enc(1, 63); spin(a.step)      # B x2 -> amount up
    amt = rd(AMT)
    magic, bamt = blk2_amt()
    print("RADIO amount=%d  block2 magic=%r ver=%d count=%d amt=%d" %
          (amt, bytes(magic), m.peek(rd(PAT_PTR) + STORE2 + 5, 1)[0],
           int.from_bytes(m.peek(rd(PAT_PTR) + STORE2 + 6, 2), "big"), bamt))
    assert bytes(magic)[:4] == b"DGX2", "block2 magic missing"
    assert bamt == amt, "block2 amount != live amount"

    # a genuine pattern reload (poke the block) must be adopted
    m.poke(rd(PAT_PTR) + STORE2 + 10, (99).to_bytes(2, "big"))
    spin(a.step)
    print("after poke block2=99 -> live amount=%d" % rd(AMT))
    assert rd(AMT) == 99, "did not adopt a block2 reload"
    print("PASS")


if __name__ == "__main__":
    sys.exit(main())
