#!/usr/bin/env python3
"""Tone+FX screenshot capture in digiemu.

Renames the current pattern to TONE+FX (every pattern slot's name field, so
whatever slot is current displays it), then captures the three FX pages on
the master page tree:
    RING.png  -> DIGI FX (kind 0)
    COMB.png  -> DIGI FILTER (kind 1), mode stepped BP -> BP2 -> COMB
    FOLD.png  -> DIGI FOLD / EQ (kind 2)
Run against dn1-2.3b. Needs the patched-Unicorn python (the digiemu venv).
"""
import argparse
import os
import struct
import sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)

WIRE = {1: (0, 2), 17: (4, 3), 18: (3, 6), 25: (2, 7)}
GUI_FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
VT_MASTER = 0x40199BAC

PAT_NAME0 = 0x41000b78     # first pattern slot's name field
PAT_STRIDE = 0x1611d       # one pattern slot
PAT_SLOTS = 128            # 8 banks x 16 patterns


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

    def frames_changed():
        if len(cap.frames) < 2:
            return False
        return cap.frames[-1] != cap.frames[-2]

    pc = spin(pc, 8_000_000)

    # ---- rename the pattern to TONE+FX (every slot's 16-byte name field) ----
    before = cap.frames[-1]
    name = b"TONE+FX" + b"\x00" * 9
    assert len(name) == 16, len(name)
    n = 0
    for i in range(PAT_SLOTS):
        at = PAT_NAME0 + i * PAT_STRIDE
        cur = m.peek(at, 8)
        if cur == b"UNTITLED":
            m.poke(at, name)
            n += 1
    print("renamed %d pattern slots to TONE+FX" % n)
    pc = spin(pc, a.step)
    changed = cap.frames[-1] != before
    print("top bar changed after rename:", changed)
    if not changed:
        # redraw needs a frame kick; spin a little more
        pc = spin(pc, a.step)
        changed = cap.frames[-1] != before
        print("top bar changed after rename (2nd spin):", changed)
    shot("00-renamed.png")

    # ---- FUNC+LFO opens the master page tree ----
    pc = btn(1, True); pc = spin(pc, a.step)
    pc = btn(25, True); pc = spin(pc, a.step)
    pc = btn(25, False); pc = spin(pc, a.step)
    pc = btn(1, False); pc = spin(pc, a.step)

    views = list(find_views(m))
    print("master views:", [hex(v) for v in views])
    assert views, "master view not found (did the page open?)"
    for view in views:
        vec = struct.unpack('>I', m.peek(view + 124, 4))[0]
        nk = (struct.unpack('>I', m.peek(view + 128, 4))[0] - vec) // 4
        kinds = [struct.unpack('>I', m.peek(vec + 4 * i, 4))[0]
                 for i in range(min(nk, 16))]
        print("view %s kinds=%s" % (hex(view), kinds))
        for want in (0, 1, 2):
            assert want in kinds, "kind %d missing" % want

        # DIGI FX (kind 0)
        m.poke(view + 144, kinds.index(0).to_bytes(4, "big"))
        pc = spin(pc, a.step)
        shot("RING.png")

        # RIGHT -> DIGI FILTER (kind 1)
        pc = btn(18, True); pc = spin(pc, 4_000_000)
        pc = btn(18, False); pc = spin(pc, a.step)
        idx = struct.unpack('>I', m.peek(view + 144, 4))[0]
        assert idx == kinds.index(1), "RIGHT did not reach DIGI FILTER (idx=%d)" % idx

        # mode: encoder B, two steps BP -> BP2 -> COMB
        f0 = cap.frames[-1]
        pc = panelin.feed(m, prof, panelin.encode_encoder(1, 48))
        pc = spin(pc, a.step)
        f1 = cap.frames[-1]
        pc = panelin.feed(m, prof, panelin.encode_encoder(1, 48))
        pc = spin(pc, a.step)
        f2 = cap.frames[-1]
        print("filter page changed per mode step:",
              f1 != f0, f2 != f1)
        shot("COMB.png")

        # RIGHT -> DIGI FOLD / EQ (kind 2)
        pc = btn(18, True); pc = spin(pc, 4_000_000)
        pc = btn(18, False); pc = spin(pc, a.step)
        idx = struct.unpack('>I', m.peek(view + 144, 4))[0]
        assert idx == kinds.index(2), "RIGHT did not reach DIGI FOLD/EQ (idx=%d)" % idx
        shot("FOLD.png")
        break

    print("PASS: RING.png / COMB.png / FOLD.png written to", a.out)


if __name__ == "__main__":
    main()