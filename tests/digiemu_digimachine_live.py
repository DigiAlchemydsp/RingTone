#!/usr/bin/env python3
"""Digi Machine (Digitone mk1, OS 1.43) - LIVE engagement test.

Runs the GUI's own emulator thread (real 48 kHz SSI renders at 64M ips) and
verifies the Stage-1 engagement path:

  1. with the selected SYN1 algorithm at 0 (FM), shared P_ON == 0;
  2. poke the selected sound's algorithm (*(0x4138E214)+0x16119) to 11, resume,
     and require shared P_ON == 1 and 64/64 non-zero machine audio frames;
  3. restore the algorithm and require P_ON back to 0.

The poke proves dmachine_render_in -> P_ON -> Core B engine -> audio end to end.
The UI path to SELECT a wavetable slot is not solved yet (see HANDOFF.md §5), so
this test pokes the confirmed storage directly.

    python tests/digiemu_digimachine_live.py --fw dn1-2.4a-8b707ef0

Needs the patched-Unicorn python (the digiemu venv), which makes audio live.
"""
import argparse
import os
import struct
import sys
import time

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")

SOUND_PTR = 0x4138E214
ALGO_OFF = 0x16119
P_ON = 0x10000000 + 0x800
A_AUDIO = 0x10000000 + 0x880


class StubOut:
    """Drains at the device rate in wall time; stands in for the sound card."""

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
    assert emu.audio_live, "live audio is required for this test"
    uc = emu._uc

    def rd(addr, n=4):
        return int.from_bytes(bytes(uc.mem_read(addr, n)), "big")

    def paused_poke(addr, v, n=4):
        emu.pause.set()
        time.sleep(0.3)
        uc.mem_write(addr, v.to_bytes(n, "big"))
        emu.pause.clear()
        time.sleep(0.6)

    def audio_stats():
        vals = struct.unpack(">64i", bytes(uc.mem_read(A_AUDIO, 0x100)))
        return sum(1 for v in vals if v), len(set(vals))

    def stable_on():
        """P_ON is written every block; poll it to avoid a torn/stale read."""
        seen = []
        for _ in range(8):
            seen.append(rd(P_ON))
            time.sleep(0.05)
        return max(set(seen), key=seen.count)

    ok = True
    base = rd(SOUND_PTR)
    assert base, "the current-sound pointer is null"
    algo0 = rd(base + ALGO_OFF)
    on0 = stable_on()
    print("start: base=0x%08x algo=0x%08x P_ON=%d (expect 0)" % (base, algo0, on0))
    ok = ok and on0 == 0

    paused_poke(base + ALGO_OFF, 11)
    algo1 = rd(base + ALGO_OFF)
    on1 = stable_on()
    nz, distinct = audio_stats()
    print("algo=11 -> P_ON=%d (expect 1), machine audio %d/64 non-zero, %d distinct"
          % (on1, nz, distinct))
    ok = ok and algo1 == 11 and on1 == 1 and nz > 0 and distinct > 1

    paused_poke(base + ALGO_OFF, algo0)
    on2 = stable_on()
    print("restored algo=0x%08x -> P_ON=%d (expect 0)" % (rd(base + ALGO_OFF), on2))
    ok = ok and on2 == 0

    emu.stop_flag.set()
    emu.join(20)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
