#!/usr/bin/env python3
"""Mix level probe: play the pattern, then for each FX set MIX 0/64/127 and
watch the output peak (and whether it hits the ceiling). Isolates a wet-path
gain / saturation at max mix.

    python tests/_probe_mix.py --fw dn1-0.9f-7148ac91 \
        --map testout/tonefx-buffx-r2-1.43.syx.map.json
"""
import argparse, json, os, struct, sys

EMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")
OUT = 0x80001A00
LIMIT = 0x740000        # the ceiling's max


def setup_env(fwdir):
    syx = [f for f in os.listdir(fwdir) if f.endswith(".syx")][0]
    os.environ.update({
        "DT2_SYX": os.path.join(fwdir, syx), "DT2_SECTIONS": fwdir + "/sections",
        "DT2_SNAPSHOTS": fwdir + "/snapshots", "DT2_PLUSDRIVE": fwdir + "/plusdrive.img",
        "DT2_MAIN_IMG": fwdir + "/sections/section_3_MAIN_OS.bin",
        "DT2_DEVICES": fwdir + "/devices" if os.path.isdir(fwdir + "/devices")
        else os.path.join(EMU, "devices")})
    return os.path.join(fwdir, syx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fw", required=True)
    ap.add_argument("--map", required=True)
    a = ap.parse_args()
    fwdir = os.path.join(EMU, "portable", "firmware", a.fw)
    syx_path = setup_env(fwdir)
    sys.path.insert(0, EMU)
    snap = fwdir + "/snapshots"
    for dp, _, fs in os.walk(snap):
        if "gui.snap" in fs:
            snap = os.path.join(dp, "gui.snap")
    sym = json.load(open(os.path.abspath(a.map)))

    from emu.session import Session
    s = Session(snap, syx_path, hle=False, strict={"stop": False})
    uc = s.m.uc

    def poke(name, v):
        uc.mem_write(int(sym[name], 16), struct.pack('>i', v))

    def stats():
        b = bytes(uc.mem_read(OUT, 512))
        peak = 0
        nclip = 0
        for i in range(0, 512, 4):
            v = int.from_bytes(b[i:i + 4], 'big', signed=True)
            if v < 0:
                v = -v
            peak = max(peak, v)
            if v >= LIMIT:
                nclip += 1
        return peak, nclip

    def settle():
        s.run_ms(160)
        return stats()

    try:
        s.tap(11, 100, 400)          # PLAY
        print("transport started")
    except Exception as e:           # noqa: BLE001
        print("PLAY failed:", e)
    s.run_ms(300)
    print("dry          peak %8d  clip %d" % stats())

    # DELAYS WRMZ / GRAINZ: no feedback first (isolate the wet level)
    for mode, on, mixn in (("WRMZ", "digiwrmz_on", "digiwrmz_mix"),
                           ("GRAINZ", "digigrainz_on", "digigrainz_mix")):
        poke("digiwrmz_mode", 0 if mode == "WRMZ" else 1)
        poke(on, 1)
        poke("digiwrmz_fb", 0); poke("digigrainz_fb", 0)
        poke("digiwrmz_mod", 0)
        for m in (0, 64, 127):
            poke(mixn, m)
            p, c = settle()
            print("DELAYS %-6s mix %3d  peak %8d  clip %d" % (mode, m, p, c))
        poke(on, 0)

    # PITCH WOB: no feedback path anyway
    poke("digiwave_fb", 0)
    poke("digiwave_page", 0); poke("digiwave_on", 1); poke("digiwave_pmode", 0)
    poke("digiwave_speed", 40); poke("digiwave_pdepth", 64)
    for m in (0, 64, 127):
        poke("digiwave_pmix", m)
        p, c = settle()
        print("PITCH  WOB    mix %3d  peak %8d  clip %d" % (m, p, c))
    # PITCH SHFT
    poke("digiwave_pmode", 96)
    for m in (0, 64, 127):
        poke("digiwave_pmix", m)
        p, c = settle()
        print("PITCH  SHFT   mix %3d  peak %8d  clip %d" % (m, p, c))
    poke("digiwave_on", 0)

    # STEREO FLAN
    poke("digiwave_page", 1); poke("digiwave_son", 1); poke("digiwave_smode", 0)
    poke("digiwave_sdepth", 64)
    for fb in (0, 96):
        poke("digiwave_fb", fb)
        for m in (0, 64, 127):
            poke("digiwave_mix", m)
            p, c = settle()
            print("STEREO FLAN fb %3d mix %3d  peak %8d  clip %d" % (fb, m, p, c))
    # STEREO WIDE
    poke("digiwave_fb", 0); poke("digiwave_smode", 106)
    for m in (0, 64, 127):
        poke("digiwave_sdepth", m)
        p, c = settle()
        print("STEREO WIDE  dep %3d       peak %8d  clip %d" % (m, p, c))
    poke("digiwave_son", 0)

    s.close()
    print("DONE")


if __name__ == "__main__":
    sys.exit(main())
