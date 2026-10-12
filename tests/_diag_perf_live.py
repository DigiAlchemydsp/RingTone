#!/usr/bin/env python3
"""PERFORM page - LIVE check (real 48 kHz SSI renders, GUI emulator thread).

Opens the master tree, switches to a DIGI page, presses UP to PERFORM, then
presses a trig pad and reads the live ring depth: it must rise and, on release,
return to the pattern value. Needs the patched-Unicorn python (digiemu venv).

    python tests/_diag_perf_live.py --fw dn1-3.2a-bd4bee18
"""
import argparse, json, os, struct, sys, time

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
VT_MASTER = 0x40199BAC
WIRE = {1: (0, 2), 15: (3, 5), 17: (4, 3), 18: (3, 6), 25: (2, 7),
        26: (3, 1), 27: (4, 0), 28: (5, 3)}


class StubOut:
    def __init__(self, rate, channels, buffers=40, block_ms=10):
        self.rate, self.block_ms, self.cap = rate, block_ms, buffers
        self.t0, self.fed, self.pending = None, 0.0, bytearray()

    def queued(self):
        return 0 if self.t0 is None else max(
            0, int((self.fed - (time.time() - self.t0)) * 1000 / self.block_ms))

    def write(self, pcm, block=False, abort=None):
        if self.t0 is None or self.queued() == 0:
            self.t0, self.fed = time.time(), 0.0
        self.pending += pcm
        size = self.rate * 4 * self.block_ms // 1000
        blocks = len(self.pending) // size
        del self.pending[:blocks * size]
        self.fed += min(blocks, self.cap - self.queued()) * self.block_ms / 1000

    def close(self):
        pass


def env(fw):
    fwdir = os.path.join(DIGIEMU, "portable", "firmware", fw)
    if not os.path.isdir(fwdir):
        raise SystemExit("firmware not found: %s" % fwdir)
    syx = [f for f in os.listdir(fwdir) if f.endswith(".syx")][0]
    os.environ.update({
        "DT2_SYX": os.path.join(fwdir, syx), "DT2_SECTIONS": fwdir + "/sections",
        "DT2_SNAPSHOTS": fwdir + "/snapshots", "DT2_PLUSDRIVE": fwdir + "/plusdrive.img",
        "DT2_MAIN_IMG": fwdir + "/sections/section_3_MAIN_OS.bin",
        "DT2_DEVICES": fwdir + "/devices" if os.path.isdir(fwdir + "/devices")
        else os.path.join(DIGIEMU, "devices")})
    os.chdir(fwdir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fw", required=True)
    a = ap.parse_args()
    env(a.fw)
    sys.path.insert(0, DIGIEMU)

    snap = None
    for dp, _, fs in os.walk(os.environ["DT2_SNAPSHOTS"]):
        if "gui.snap" in fs:
            snap = os.path.join(dp, "gui.snap")

    from emu import audioout, gui
    gui.audioout.WaveOut = StubOut
    emu = gui.Emulator(os.path.abspath(snap))
    emu.start()
    emu.ready.wait(300)
    time.sleep(2.0)
    assert emu.audio_live, "live audio is required for this test"
    uc = emu._uc

    sym = json.load(open(os.path.join(os.path.dirname(__file__), "..", "testout",
                                      "test-3.2a.syx.map.json")))
    G_DEPTH = int(sym["digiring_depth"], 16)

    def rd(addr, n=4):
        return int.from_bytes(bytes(uc.mem_read(addr, n)), "big")

    def key(code, hold=0.4):
        emu.inbox.append(('press', code, 0)); time.sleep(hold)
        emu.inbox.append(('release', code, 0)); time.sleep(0.6)

    def hold(code):
        emu.inbox.append(('press', code, 0)); time.sleep(1.0)

    def rel(code):
        emu.inbox.append(('release', code, 0)); time.sleep(1.0)

    def find_view():
        for base in range(0x40000000, 0x44000000, 0x100000):
            try:
                data = bytes(uc.mem_read(base, 0x100000))
            except Exception:
                continue
            off = data.find(struct.pack('>I', VT_MASTER))
            while off >= 0:
                if base + off >= 0x41000000:
                    return base + off
                off = data.find(struct.pack('>I', VT_MASTER), off + 1)
        return None

    # FUNC + LFO opens the master page tree
    hold(1); hold(25); rel(25); rel(1)
    time.sleep(0.6)
    view = find_view()
    assert view, "master view not found"
    emu.pause.set(); time.sleep(0.3)
    vec = rd(view + 124)
    nk = (rd(view + 128) - vec) // 4
    kinds = [rd(vec + 4 * i) for i in range(nk)]
    print("kinds:", kinds)
    assert 6 in kinds and 0 in kinds
    uc.mem_write(view + 144, kinds.index(0).to_bytes(4, "big"))
    emu.pause.clear(); time.sleep(0.6)
    print("on DIGI RING, depth =", rd(G_DEPTH))

    key(15)                                  # UP -> PERFORM
    emu.pause.set(); time.sleep(0.3)
    idx = rd(view + 144)
    emu.pause.clear()
    print("after UP: idx=%d kind=%d" % (idx, kinds[idx]))
    assert kinds[idx] == 6, "UP did not reach PERFORM"

    base = rd(G_DEPTH)
    hold(26)                                 # trig 1: ring, intensity 1
    time.sleep(0.5)
    hi = rd(G_DEPTH)
    print("holding trig1: depth %d -> %d (target %d)" % (base, hi, base + (127 - base) // 4))
    rel(26)
    time.sleep(0.5)
    back = rd(G_DEPTH)
    print("released trig1: depth -> %d" % back)
    assert hi > base, "pad did not raise the depth"
    assert back == base, "release did not restore the depth"

    hold(28)                                 # trig 3: fold/crush, intensity 1
    G_FOLD = int(sym["digifold_amount"], 16)
    G_CON = int(sym["digicrush_amount"], 16)
    fb = rd(G_FOLD)
    time.sleep(0.5)
    print("holding trig3: fold %d -> %d, crush -> %d" %
          (fb, rd(G_FOLD), rd(G_CON)))
    rel(28)
    time.sleep(0.4)
    print("released trig3: fold -> %d, crush -> %d" % (rd(G_FOLD), rd(G_CON)))

    emu.stop_flag.set(); emu.join(20)
    print("PASS")


if __name__ == "__main__":
    sys.exit(main())
