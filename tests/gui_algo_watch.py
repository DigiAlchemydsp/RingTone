#!/usr/bin/env python3
"""Digitone panel with a memory-write logger for the SYN1 algorithm hunt.

Runs the normal Digitone window, but after the emulator is up installs a Unicorn
memory-write hook that logs writes whose value looks like a small algorithm
number (0..16) in the main RAM span, plus writes to the selected sound. Lets the
operator drive the real panel while the terminal sees where the algorithm lands.

    python tests/gui_algo_watch.py SNAPSHOT
"""
import os
import struct
import sys
import threading
import time

DIGIEMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
sys.path.insert(0, DIGIEMU)

from emu import dtpanel  # noqa: E402
from emu.dnpanel import DigitonePanel  # noqa: E402
from unicorn import UC_HOOK_MEM_WRITE  # noqa: E402
from unicorn.m68k_const import UC_M68K_REG_PC  # noqa: E402

SOUND_PTR = 0x4138E214
ALGO_OFF = 0x16119
P_ON = 0x10000000 + 0x800


def main(argv):
    snap = argv[0] if argv else None

    panel = None
    orig_run = DigitonePanel.__init__

    def patched_init(self, *a, **k):
        orig_run(self, *a, **k)
        monitor(self)
        panel = self

    DigitonePanel.__init__ = patched_init

    def monitor(self):
        def worker():
            emu = self.emu
            emu.ready.wait(300)
            time.sleep(1.0)
            uc = emu._uc
            if uc is None:
                print("[watch] no uc", flush=True)
                return
            seen = {"n": 0}

            def hook(u, access, address, size, value, data):
                # log only sound/pattern-region writes of a plausible algorithm
                # value (0..24), skipping the audio/stack/heap noise.
                if size == 4 and 0x40000000 <= address < 0x41000000 \
                        and 0 <= value <= 24:
                    seen["n"] += 1
                    if seen["n"] <= 4000:
                        try:
                            pc = u.reg_read(UC_M68K_REG_PC)
                        except Exception:
                            pc = 0
                        print("[watch] addr=0x%08x size=%d val=%d pc=0x%08x"
                              % (address, size, value, pc), flush=True)

            try:
                uc.hook_add(UC_HOOK_MEM_WRITE, hook)
                print("[watch] write hook installed", flush=True)
            except Exception as exc:
                print("[watch] hook failed: %s" % exc, flush=True)

            # live poll of the candidate addresses
            last = None
            while not emu.stop_flag.is_set():
                try:
                    base = int.from_bytes(bytes(uc.mem_read(SOUND_PTR, 4)), "big")
                    algo = int.from_bytes(bytes(uc.mem_read(base + ALGO_OFF, 4)), "big") if base else -1
                    on = int.from_bytes(bytes(uc.mem_read(P_ON, 4)), "big")
                    cur = (base, algo, on)
                    if cur != last:
                        print("[poll] base=0x%08x algo=%d P_ON=%d" % cur, flush=True)
                        last = cur
                except Exception:
                    pass
                time.sleep(0.4)

        threading.Thread(target=worker, daemon=True).start()

    return dtpanel.run(argv, DigitonePanel, prog='gui_algo_watch',
                       description='Digitone panel with algorithm watch.')


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
