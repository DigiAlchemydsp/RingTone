#!/usr/bin/env python3
"""PERFORM page diagnostic (digiemu): open the master tree, go to a DIGI page,
press UP to reach PERFORM, step encoder A, hold a trig, and check the page and
the per-pattern store. Run with the patched-Unicorn venv."""
import argparse, json, os, struct, sys

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)
FLAGS = dict(unblock=True, softfloat=True, bitmap=True, dsp=True)
VT_MASTER = 0x40199BAC
PAT_PTR = 0x4138E214
STORE_OFF = 0x1040

# code -> [channel, bit] (devices/digitone.toml)
WIRE = {1: (0, 2), 15: (3, 5), 17: (4, 3), 18: (3, 6), 25: (2, 7),
        26: (3, 1), 27: (4, 0), 34: (5, 1), 35: (5, 2)}


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
    ap.add_argument("--out", default="perf_out")
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
        pc, _e, _w = longrun.spin(m, pc, n, pits=pits)
        return pc

    def btn(code, down):
        nonlocal pc
        ch, bit = WIRE[code]
        pc = panelin.feed(m, prof, panelin.encode_buttons(
            ch, (1 << bit) if down else 0))

    def tap(code, n=None):
        btn(code, True); spin(n or a.step)
        btn(code, False); spin(n or a.step)

    def shot(name):
        if cap.frames:
            panel.write_png(cap.frames[-1], os.path.join(a.out, name), scale=6)
            print("  wrote", name)

    def rd(addr, n=4):
        return int.from_bytes(m.peek(addr, n), "big")

    def store_param(i):
        base = rd(PAT_PTR)
        return int.from_bytes(m.peek(base + STORE_OFF + 8 + 2 * i, 2), "big")

    # live mod globals: read the patch's symbol map (testout/*.map.json)
    mp = os.path.join(os.path.dirname(__file__), "..", "testout",
                      "test-3.2a.syx.map.json")
    sym = json.load(open(mp))
    G_DEPTH = int(sym["digiring_depth"], 16)
    G_FOLD = int(sym["digifold_amount"], 16)
    G_TAKEN = int(sym["pf_taken"], 16)
    G_HOLD = int(sym["pf_holdmask"], 16)
    G_RUN = int(sym["pf_running"], 16)
    G_H = {"cur": int(sym["pf_cur"], 16), "tgt": int(sym["pf_tgt"], 16),
           "base": int(sym["pf_base"], 16), "act": int(sym["pf_active"], 16),
           "cout": int(sym["dc_out"], 16), "phase": int(sym["di_phase"], 16)}

    def r32(addr):
        return int.from_bytes(m.peek(addr, 4), "big")

    spin(8_000_000)
    print("start: pattern=0x%08x" % rd(PAT_PTR))

    # FUNC + LFO opens the master page tree
    btn(1, True); spin(a.step)
    btn(25, True); spin(a.step)
    btn(25, False); spin(a.step)
    btn(1, False); spin(a.step)

    view = next(find_views(m))
    vec = rd(view + 124)
    nk = (rd(view + 128) - vec) // 4
    kinds = [rd(vec + 4 * i) for i in range(nk)]
    print("kinds:", kinds)
    assert 6 in kinds, "PERFORM (kind 6) missing"
    assert 0 in kinds, "DIGI RING (kind 0) missing"

    # sit on DIGI RING, then UP -> PERFORM
    m.poke(view + 144, kinds.index(0).to_bytes(4, "big"))
    spin(a.step)
    shot("00-ring.png")
    tap(15)
    idx = rd(view + 144)
    print("after UP: idx=%d kind=%d" % (idx, kinds[idx]))
    assert kinds[idx] == 6, "UP did not reach PERFORM"
    shot("01-perf.png")

    base_depth = store_param(1)
    print("store ring depth (base):", base_depth)

    # encoder A up: ring depth should rise and persist
    pc = panelin.feed(m, prof, panelin.encode_encoder(0, 16))
    spin(a.step)
    enc_depth = store_param(1)
    print("after enc A +16: store ring depth =", enc_depth)
    assert enc_depth > base_depth, "encoder A did not raise ring depth"
    shot("02-enca.png")

    # hold trig 1 (ring, intensity 1): the press engages a pad whose target is
    # above the pattern value, and the store must NOT move. The live depth ramp
    # is verified separately in _diag_perf_live.py (the headless run does not
    # drive the audio render).
    held = store_param(1)
    btn(26, True); spin(a.step)
    print("  taken=0x%x hold=0x%x run=%d | cur=%d tgt=%d base=%d" %
          (r32(G_TAKEN), r32(G_HOLD), r32(G_RUN), r32(G_H["cur"]),
           r32(G_H["tgt"]), r32(G_H["base"])))
    assert r32(G_TAKEN) & 1, "trig press was not taken"
    assert r32(G_HOLD) & 1, "trig pad did not engage"
    assert r32(G_H["tgt"]) > r32(G_H["base"]), "pad target did not rise"
    assert store_param(1) == held, "momentary pad wrote the store"
    shot("03-trig1.png")
    btn(26, False); spin(a.step)
    print("released trig1: store =", store_param(1), "(was", held, ")")
    assert not (r32(G_TAKEN) & 1), "trig release was not consumed"
    assert store_param(1) == held, "release moved the store"
    shot("04-release.png")

    # UP again returns to the page we came from
    tap(15)
    idx = rd(view + 144)
    print("after UP back: idx=%d kind=%d" % (idx, kinds[idx]))
    assert kinds[idx] == 0, "UP did not return to DIGI RING"

    print("PASS")


if __name__ == "__main__":
    sys.exit(main())
