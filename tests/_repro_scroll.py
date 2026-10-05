#!/usr/bin/env python3
"""Reproduce the operator's UI scroll (encoder A) in the GUI worker and read
the selected sound's algorithm + shared P_ON + machine audio after each step."""
import argparse, os, struct, sys, time

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
SOUND_PTR = 0x4138E214
ALGO_OFF = 0x16119
P_ON = 0x10000000 + 0x800
A_AUDIO = 0x10000000 + 0x880


class StubOut:
    def __init__(self, rate, channels, buffers=40, block_ms=10):
        self.rate, self.block_ms, self.cap = rate, block_ms, buffers
        self.bytes = self.dropped = 0
        self.t0, self.fed = None, 0.0
        self.pending = bytearray()

    def queued(self):
        if self.t0 is None:
            return 0
        return max(0, int((self.fed - (time.time() - self.t0)) * 1000 / self.block_ms))

    def write(self, pcm, block=False, abort=None):
        now = time.time()
        if self.t0 is None or self.queued() == 0:
            self.t0, self.fed = now, 0.0
        self.pending += pcm
        size = self.rate * 4 * self.block_ms // 1000
        blocks = len(self.pending) // size
        del self.pending[:blocks * size]
        take = min(blocks, self.cap - self.queued())
        self.dropped += blocks - take
        self.fed += take * self.block_ms / 1000
        self.bytes += len(pcm)

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
    return fwdir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fw", required=True)
    ap.add_argument("--rot", type=int, default=1, help="encoder rotation code")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--delta", type=int, default=-4)
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
    print("audio_live:", emu.audio_live, "error:", emu.error)
    uc = emu._uc

    def rd(addr, n=4):
        return int.from_bytes(bytes(uc.mem_read(addr, n)), "big")

    base = rd(SOUND_PTR)
    print("base=0x%08x algo=%d P_ON=%d" % (base, rd(base + ALGO_OFF), rd(P_ON)))

    for i in range(a.steps):
        emu.inbox.append(("encoder", a.rot, a.delta))
        time.sleep(0.35)
        algo = rd(base + ALGO_OFF)
        on = rd(P_ON)
        if algo != 0 or on:
            vals = struct.unpack(">64i", bytes(uc.mem_read(A_AUDIO, 0x100)))
            nz = sum(1 for v in vals if v)
            print("step %2d: algo=%-3d P_ON=%d audio_nz=%d/64" % (i, algo, on, nz))
        elif i % 5 == 0:
            print("step %2d: algo=%-3d P_ON=%d" % (i, algo, on))

    emu.stop_flag.set()
    emu.join(20)
    return 0


if __name__ == "__main__":
    sys.exit(main())
