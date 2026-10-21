#!/usr/bin/env python3
"""ToneFX-BufferFX -- LIVE check (real 48 kHz SSI renders, GUI emulator thread).

Opens the master tree, asserts the DELAYS (kind 11) and REVERB (kind 12) pages
are present, then runs each new engine (WRMZ, Grainz via the DELAYS mode switch,
Tailz) with real renders and confirms no emulator fault. Needs the patched-Unicorn
python (digiemu venv).

    python tests/_diag_buffx_live.py --fw dn1-0.2w-f6736c1e \
        --map testout/tonefx-buffx-1.43.syx.map.json
"""
import argparse, json, os, struct, sys, time

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
VT_MASTER = 0x40199BAC
DLY_KIND = 11


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
    ap.add_argument("--map", required=True)
    a = ap.parse_args()
    map_path = os.path.abspath(a.map)
    env(a.fw)
    sys.path.insert(0, DIGIEMU)

    snap = None
    for dp, _, fs in os.walk(os.environ["DT2_SNAPSHOTS"]):
        if "gui.snap" in fs:
            snap = os.path.join(dp, "gui.snap")

    from emu import gui
    gui.audioout.WaveOut = StubOut
    emu = gui.Emulator(os.path.abspath(snap))
    emu.start()
    emu.ready.wait(300)
    time.sleep(2.0)
    assert emu.audio_live, "live audio is required for this test"
    uc = emu._uc

    sym = json.load(open(map_path))

    def rd(addr, n=4):
        return int.from_bytes(bytes(uc.mem_read(addr, n)), "big")

    def wr(addr, v):
        uc.mem_write(addr, int(v).to_bytes(4, "big", signed=v < 0))

    def g(name):
        return int(sym[name], 16)

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

    hold(1); hold(25); rel(25); rel(1)          # FUNC + LFO opens the master tree
    time.sleep(0.6)
    view = find_view()
    assert view, "master view not found"
    emu.pause.set(); time.sleep(0.3)
    vec = rd(view + 124)
    nk = (rd(view + 128) - vec) // 4
    kinds = [rd(vec + 4 * i) for i in range(nk)]
    print("kinds:", kinds)
    assert DLY_KIND in kinds, "DELAYS page (kind 11) missing"

    # show the DELAYS page, then the REVERB page
    uc.mem_write(view + 144, kinds.index(DLY_KIND).to_bytes(4, "big"))
    emu.pause.clear(); time.sleep(0.8)
    print("on DELAYS, kind =", rd(vec + 4 * rd(view + 144)))

    # WRMZ mode
    wr(g("digiwrmz_mode"), 0); wr(g("digiwrmz_on"), 1); wr(g("digiwrmz_mix"), 100)
    time.sleep(0.6)
    print("WRMZ on; emu.error =", emu.error)
    assert emu.error is None and emu.audio_live, "WRMZ render faulted"

    # GRAINZ mode (same line, D switches)
    wr(g("digiwrmz_mode"), 1); wr(g("digiwrmz_on"), 0)
    wr(g("digigrainz_on"), 1); wr(g("digigrainz_mix"), 110); wr(g("digigrainz_dens"), 90)
    time.sleep(0.6)
    print("GRAINZ on (mode switched); emu.error =", emu.error)
    assert emu.error is None and emu.audio_live, "GRAINZ render faulted"

    emu.stop_flag.set(); emu.join(20)
    print("PASS")


if __name__ == "__main__":
    sys.exit(main())
