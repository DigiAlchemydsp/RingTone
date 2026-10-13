#!/usr/bin/env python3
"""LIVE: with the ramp-snap fix, disabling FLAN must drive its mix to exactly 0
(true bypass, stops writing feedback), so the PITCH modes are not distorted."""
import argparse, json, os, struct, sys, time

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
VT_MASTER = 0x40199BAC


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
    a = ap.parse_args()
    env(a.fw)
    sys.path.insert(0, DIGIEMU)
    snap = [os.path.join(dp, f) for dp, _, fs in os.walk(os.environ["DT2_SNAPSHOTS"])
            for f in fs if f == "gui.snap"][0]
    from emu import audioout, gui
    gui.audioout.WaveOut = StubOut
    emu = gui.Emulator(os.path.abspath(snap))
    emu.start(); emu.ready.wait(300); time.sleep(2.0)
    assert emu.audio_live
    uc = emu._uc
    sym = json.load(open(os.path.join(os.path.dirname(__file__), "..", "testout",
                                      "test-3.5d.syx.map.json")))
    MIX = int(sym["wv_fla_mix"], 16)
    SON = int(sym["digiwave_son"], 16)
    PG = int(sym["digiwave_page"], 16)

    def rd(x):
        return int.from_bytes(bytes(uc.mem_read(x, 4)), "big")

    emu.inbox.append(('press', 1, 0)); time.sleep(0.4)
    emu.inbox.append(('press', 25, 0)); time.sleep(0.4)
    emu.inbox.append(('release', 25, 0)); time.sleep(0.4)
    emu.inbox.append(('release', 1, 0)); time.sleep(0.8)
    view = None
    for base in range(0x40000000, 0x44000000, 0x100000):
        data = bytes(uc.mem_read(base, 0x100000))
        off = data.find(struct.pack('>I', VT_MASTER))
        if off >= 0 and base + off >= 0x41000000:
            view = base + off
            break
    emu.pause.set(); time.sleep(0.3)
    vec = rd(view + 124); n = (rd(view + 128) - vec) // 4
    kinds = [rd(vec + 4 * i) for i in range(n)]
    uc.mem_write(view + 144, kinds.index(5).to_bytes(4, "big"))   # STEREO page (FLAN)
    emu.pause.clear(); time.sleep(0.6)
    print("fla_mix off start:", rd(MIX))
    emu.inbox.append(('encoder', 1, 40)); time.sleep(1.0)         # A on
    emu.inbox.append(('encoder', 8, 40)); time.sleep(1.2)         # H feedback up
    print("fla_mix on:", rd(MIX))
    emu.inbox.append(('encoder', 1, -40)); time.sleep(1.5)        # A off
    print("after A off: son=%d page=%d fla_mix=%d" % (rd(SON), rd(PG), rd(MIX)))
    assert rd(MIX) == 0, "FLAN mix did not reach 0 -> not bypassed"
    emu.stop_flag.set(); emu.join(20)
    print("PASS")


if __name__ == "__main__":
    sys.exit(main())
