#!/usr/bin/env python3
"""Check LEFT/RIGHT navigation rotates the whole master page vector and never
gets stuck (including while sitting on a stock page for a long time)."""
import argparse, os, struct, sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)
WIRE = {1: (0, 2), 25: (2, 7), 17: (4, 3), 18: (3, 6)}
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
VT_MASTER = 0x40199BAC


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


def find_views(m):
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

    def spin(n):
        nonlocal pc
        pc, _e, _w = longrun.spin(m, pc, n, pits=pits)

    def btn(code, down):
        ch, bit = WIRE[code]
        return panelin.feed(m, prof, panelin.encode_buttons(ch, (1 << bit) if down else 0))

    def idx(view):
        return struct.unpack('>I', m.peek(view + 144, 4))[0]

    spin(8_000_000)
    pc = btn(1, True); spin(18_000_000)
    pc = btn(25, True); spin(18_000_000)
    pc = btn(25, False); spin(18_000_000)
    pc = btn(1, False); spin(18_000_000)
    view = next(find_views(m))
    vec = struct.unpack('>I', m.peek(view + 124, 4))[0]
    nk = (struct.unpack('>I', m.peek(view + 128, 4))[0] - vec) // 4
    kinds = [struct.unpack('>I', m.peek(vec + 4 * i, 4))[0] for i in range(nk)]
    print("kinds:", kinds, "n=", nk)

    ok = True

    # sit on a stock page for a long time, then RIGHT must still work
    m.poke(view + 144, (0).to_bytes(4, "big"))
    spin(80_000_000)
    before = idx(view)
    pc = btn(18, True); spin(6_000_000); pc = btn(18, False); spin(10_000_000)
    after = idx(view)
    print("stock page long-sit: RIGHT %d -> %d %s" % (before, after,
          "OK" if after == (before + 1) % nk else "FAIL"))
    ok = ok and after == (before + 1) % nk

    # walk RIGHT all the way round, back to start
    start = after
    seen = [after]
    for _ in range(nk - 1):
        pc = btn(18, True); spin(4_000_000); pc = btn(18, False); spin(8_000_000)
        seen.append(idx(view))
    print("RIGHT cycle:", seen, "OK" if seen == [(start + i) % nk for i in range(nk)] else "FAIL")
    ok = ok and seen == [(start + i) % nk for i in range(nk)]

    # LEFT one step
    cur = idx(view)
    pc = btn(17, True); spin(4_000_000); pc = btn(17, False); spin(8_000_000)
    print("LEFT:", idx(view), "OK" if idx(view) == (cur + nk - 1) % nk else "FAIL")
    ok = ok and idx(view) == (cur + nk - 1) % nk

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
