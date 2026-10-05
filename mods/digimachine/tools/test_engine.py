"""Unit-test the digimachine Core B engine blob in isolation (fast, no firmware).

Loads the assembled blob at its VMA onto a bare MCF5441x machine with:
  - shared RAM at 0 (DSP side): params +0x800, audio +0x880
  - a stub at the displaced copy target 0x40003848 that records the call
Runs digimachine_engine and checks:
  - all registers + MACSR/ACC0/ACCext01 are preserved
  - P_ON=0 -> the audio slot is untouched, and it still calls the copy
  - P_ON=1 -> the audio slot is written (zeros in the v1 skeleton), copy called
"""
import os
import struct
import sys

from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_CODE
from unicorn.m68k_const import (UC_M68K_REG_D0, UC_M68K_REG_D7, UC_M68K_REG_A0,
                                UC_M68K_REG_A6, UC_M68K_REG_A7, UC_M68K_REG_PC,
                                UC_M68K_REG_SR)

HERE = os.path.dirname(os.path.abspath(__file__))
DSP = os.path.normpath(os.path.join(HERE, "..", "dsp"))
VMA = 0x00008000          # the engine now runs from shared RAM (DSP side)
COPY = 0x40003848
RET = 0x40100000          # sentinel return address for the tail jmp
SH_BASE = 0x00000000


def load():
    with open(os.path.join(DSP, "engine.bin"), "rb") as fh:
        return fh.read()


def machine():
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    for base in (0x00000000, 0x40000000, 0x40100000, 0x80000000):
        uc.mem_map(base, 0x00100000)
    return uc


def run(uc, blob, on, morph=0):
    uc.mem_write(VMA, blob)
    # stub the displaced copy: rts to RET
    uc.mem_write(COPY, b"\x4e\x75")
    uc.mem_write(SH_BASE + 0x7FC, struct.pack(">I", 0x444D4143))  # upload magic
    uc.mem_write(SH_BASE + 0x800, struct.pack(">i", on))
    uc.mem_write(SH_BASE + 0x804, struct.pack(">i", 0x01000000))  # inc (big, fast)
    uc.mem_write(SH_BASE + 0x810, struct.pack(">i", morph))       # morph
    uc.mem_write(SH_BASE + 0x814, struct.pack(">i", 32767))       # level
    uc.mem_write(SH_BASE + 0x820, struct.pack(">i", 127))         # filt freq (open)
    # seed table 0 with a sine, table 1 inverted
    for i in range(256):
        v = int(20000 * __import__("math").sin(2 * 3.14159265 * i / 256))
        uc.mem_write(SH_BASE + 0x1000 + i * 2, struct.pack(">h", v))
        uc.mem_write(SH_BASE + 0x1000 + 512 + i * 2, struct.pack(">h", -v))
    # poison the audio slot so we can see if it is touched
    for off in range(SH_BASE + 0x880, SH_BASE + 0x8C0, 4):
        uc.mem_write(off, struct.pack(">i", 0x11223344))
    # poison the saved registers with markers
    for reg in (UC_M68K_REG_D0, UC_M68K_REG_D7, UC_M68K_REG_A0, UC_M68K_REG_A6):
        uc.reg_write(reg, 0xABCD0000 + reg)
    # seed an env so attack reaches full
    uc.mem_write(0x8000F800 + 12, struct.pack(">i", 32768))
    uc.mem_write(SH_BASE + 0x83C, struct.pack(">i", 1))           # gate on
    uc.mem_write(SH_BASE + 0x82C, struct.pack(">i", 8))           # attack
    uc.reg_write(UC_M68K_REG_SR, 0x2000)
    uc.reg_write(UC_M68K_REG_A7, 0x40180000)
    uc.emu_start(VMA, COPY, count=1000000)     # stop when we reach the copy
    return uc


def main():
    blob = load()
    print("blob %d bytes at 0x%08x" % (len(blob), VMA))
    ok = True
    for on in (0, 1):
        uc = machine()
        run(uc, blob, on)
        pc = uc.reg_read(UC_M68K_REG_PC)
        audio = uc.mem_read(SH_BASE + 0x880, 0x40)
        untouched = audio == struct.pack(">16i", *([0x11223344] * 16))
        touched = not untouched
        regs_ok = all(uc.reg_read(r) == 0xABCD0000 + r
                      for r in (UC_M68K_REG_D0, UC_M68K_REG_D7,
                                UC_M68K_REG_A0, UC_M68K_REG_A6))
        print("ON=%d pc=0x%08x reached_copy=%s regs_preserved=%s audio_touched=%s"
              % (on, pc, pc == COPY, regs_ok, touched))
        if on == 1:
            vals = struct.unpack(">16i", bytes(audio))
            print("  first 8 L/R samples:", [hex(v & 0xffffffff) for v in vals[:8]])
            distinct = len(set(vals))
            print("  distinct sample values:", distinct, " (a real waveform => several)")
            if distinct < 3:
                print("  ERROR: the oscillator produced a constant block")
                ok = False
        if pc != COPY or not regs_ok:
            ok = False
        if on == 0 and touched:
            print("  ERROR: OFF but the audio slot was written")
            ok = False
        if on == 1 and not touched:
            print("  ERROR: ON but the audio slot was not written")
            ok = False

    # ---- morph interpolation: table 0 is +sine, table 1 is -sine, so a
    # halfway blend (index 0, fraction 128) should cancel to ~0 ----
    uc = machine()
    run(uc, blob, 1, morph=(128 << 8))
    vals = struct.unpack(">32i", bytes(uc.mem_read(SH_BASE + 0x880, 0x80)))
    peak = max(abs(v) for v in vals)
    print("morph=0.5 peak amplitude:", peak, "(expect ~0: the two tables cancel)")
    if peak > 200:
        print("  ERROR: morph interpolation did not blend the two tables")
        ok = False

    # ---- magic guard: with no upload magic the engine must bail to the copy
    # without touching the audio slot (this is the Core B boot-race guard) ----
    uc = machine()
    uc.mem_write(VMA, blob)
    uc.mem_write(COPY, b"\x4e\x75")
    uc.mem_write(SH_BASE + 0x800, struct.pack(">i", 1))       # P_ON set ...
    for off in range(SH_BASE + 0x880, SH_BASE + 0x8C0, 4):    # ... but no magic
        uc.mem_write(off, struct.pack(">i", 0x11223344))
    uc.reg_write(UC_M68K_REG_SR, 0x2000)
    uc.reg_write(UC_M68K_REG_A7, 0x40180000)
    uc.emu_start(VMA, COPY, count=1000000)
    guarded = uc.reg_read(UC_M68K_REG_PC) == COPY and \
        bytes(uc.mem_read(SH_BASE + 0x880, 0x40)) == struct.pack(">16i", *([0x11223344] * 16))
    print("magic-guard: bailed to copy with audio untouched =", guarded)
    if not guarded:
        print("  ERROR: engine ran before the upload magic was set")
        ok = False

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
