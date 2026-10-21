#!/usr/bin/env python3
"""Dump the 128x64 1bpp panel for the RING (kind 0) and DELAYS (kind 11) pages
as ASCII, to eyeball the 3.6 UI pass. Patched-Unicorn venv; see BUILDING.md."""
import argparse, os, struct, sys, time

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
VT_MASTER = 0x40199BAC
FBP = 0x40241A44


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
        n = len(self.pending) // size
        del self.pending[:n * size]
        self.fed += min(n, self.cap - self.queued()) * self.block_ms / 1000

    def close(self):
        pass


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fw", required=True)
    a = ap.parse_args()
    env(a.fw)
    sys.path.insert(0, DIGIEMU)

    from emu import gui
    gui.audioout.WaveOut = StubOut
    snap = None
    for dp, _, fs in os.walk(os.environ["DT2_SNAPSHOTS"]):
        if "gui.snap" in fs:
            snap = os.path.join(dp, "gui.snap")
    emu = gui.Emulator(os.path.abspath(snap))
    emu.start()
    emu.ready.wait(300)
    time.sleep(2.0)
    uc = emu._uc

    def rd(addr, n=4):
        return int.from_bytes(bytes(uc.mem_read(addr, n)), "big")

    def key(code, hold=0.4):
        emu.inbox.append(('press', code, 0)); time.sleep(hold)
        emu.inbox.append(('release', code, 0)); time.sleep(0.6)

    def hold(code):
        emu.inbox.append(('press', code, 0)); time.sleep(1.0)

    def rel(code):
        emu.inbox.append(('release', code, 0)); time.sleep(1.0)

    hold(1); hold(25); rel(25); rel(1)     # FUNC + LFO opens the master tree
    time.sleep(0.6)
    # find the master view
    view = None
    for base in range(0x40000000, 0x44000000, 0x100000):
        try:
            data = bytes(uc.mem_read(base, 0x100000))
        except Exception:
            continue
        off = data.find(struct.pack('>I', VT_MASTER))
        while off >= 0:
            if base + off >= 0x41000000:
                view = base + off
                break
            off = data.find(struct.pack('>I', VT_MASTER), off + 1)
        if view:
            break
    assert view, "master view not found"
    emu.pause.set(); time.sleep(0.3)
    vec = rd(view + 124)
    nk = (rd(view + 128) - vec) // 4
    kinds = [rd(vec + 4 * i) for i in range(nk)]
    print("kinds:", kinds)

    def dump(idx, label):
        uc.mem_write(view + 144, idx.to_bytes(4, "big"))
        emu.pause.clear(); time.sleep(1.0)
        emu.pause.set(); time.sleep(0.2)
        p = rd(FBP)
        fb = bytes(uc.mem_read(p, 1024))
        print("\n== %s (index %d, kind %d) ==" % (label, idx, kinds[idx]))
        for y in range(63, -1, -1):
            row = "".join('#' if (fb[(7 - (y >> 3)) + (x << 3)] >> (y & 7)) & 1 else '.'
                          for x in range(128))
            print(row)
        emu.pause.clear()

    dump(kinds.index(0), "RING")        # DN_FXKIND = 0
    dump(kinds.index(11), "DELAYS")     # DN_DLYKIND = 11

    emu.stop_flag.set(); emu.join(20)
    print("\nDONE")


if __name__ == "__main__":
    sys.exit(main())
