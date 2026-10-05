#!/usr/bin/env python3
"""Live decisive test: run the GUI worker (real 48 kHz render, 64M ips), pause,
poke the documented algorithm address (and a small range), resume, and read
shared P_ON. Finds the engagement address and proves the render path."""
import argparse, os, struct, sys, tempfile, time

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
    ap.add_argument("--scan", action="store_true")
    a = ap.parse_args()
    fwdir = env(a.fw)
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

    def paused_poke(addr, val, n=4):
        emu.pause.set()
        time.sleep(0.3)
        uc.mem_write(addr, val.to_bytes(n, "big"))
        emu.pause.clear()
        time.sleep(0.5)

    base = rd(SOUND_PTR)
    print("base=0x%08x algo=0x%08x P_ON=%d"
          % (base, rd(base + ALGO_OFF), rd(P_ON)))

    # documented address
    paused_poke(base + ALGO_OFF, 11)
    print("poke base+0x16119=11 -> algo=0x%08x P_ON=%d render_audio_nz=%d"
          % (rd(base + ALGO_OFF), rd(P_ON),
             sum(1 for v in struct.unpack(">64i", bytes(uc.mem_read(A_AUDIO, 0x100))) if v)))

    if a.scan:
        for off in range(ALGO_OFF - 0x40, ALGO_OFF + 0x44, 4):
            old = rd(base + off)
            paused_poke(base + off, 11)
            on = rd(P_ON)
            paused_poke(base + off, old)
            if on == 1:
                print("  ENGAGE at base+0x%x (old=0x%08x)" % (off, old))

    emu.stop_flag.set()
    emu.join(20)
    return 0


if __name__ == "__main__":
    sys.exit(main())
