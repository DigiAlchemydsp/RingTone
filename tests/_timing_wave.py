#!/usr/bin/env python3
"""Per-mode cftiming probe for the digiwave PITCH / STEREO block. Same clock as
_timing_buffx.py: all-off, then each wave mode, reports the worst block cost.

    python tests/_timing_wave.py --fw dn1-0.9h-306fe43f \
        --map testout/exp-1.43.syx.map.json --ms 120
"""
import argparse, json, os, struct, sys

EMU = os.environ.get("DIGIEMU", r"C:\Users\benan\Music\ELEKTRON\digiemu-main")


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
    ap.add_argument("--ms", type=int, default=120)
    a = ap.parse_args()
    map_path = os.path.abspath(a.map)
    fwdir = os.path.join(EMU, "portable", "firmware", a.fw)
    if not os.path.isdir(fwdir):
        raise SystemExit("firmware not found: %s" % fwdir)
    syx_path = setup_env(fwdir)
    sys.path.insert(0, EMU)

    snap = os.path.join(fwdir, "snapshots")
    for dp, _, fs in os.walk(snap):
        if "gui.snap" in fs:
            snap = os.path.join(dp, "gui.snap")

    from emu import cftiming, device as devmod, ssi
    from emu.session import Session

    dev, _ = devmod.identify(syx_path)
    s = Session(snap, syx_path, hle=False, timing={"accel": "max"},
                strict={"stop": False})
    sym = json.load(open(map_path))
    uc = s.m.uc

    def poke(name, v):
        uc.mem_write(int(sym[name], 16), struct.pack('>i', v))

    dma = s.sources[0] if s.sources else None
    tx = dma.p.tx_vector
    forced = ssi.FORCE_VECTOR

    def n_run(v):
        k = s.clock.vectors.get(v)
        return k.count if k else 0

    def report(v, n0):
        k = s.clock.vectors.get(v)
        if not k:
            return None
        w = list(k.walls)[n0:]
        if not w:
            return None
        sw = sorted(w)
        return {"worst": sw[-1], "p99": sw[min(len(sw) - 1, int(len(sw) * 0.99))],
                "mean": round(sum(w) / len(w), 1),
                "margin": round(1 - sw[-1] / period, 4),
                "late": sum(1 for x in w if x > period)}

    def set_wave(page, on, pmode=0, smode=0, depth=100, speed=64, fb=0):
        poke("digiwave_page", page)
        poke("digiwave_on", 1 if (page == 0 and on) else 0)
        poke("digiwave_son", 1 if (page == 1 and on) else 0)
        poke("digiwave_pmode", pmode)
        poke("digiwave_smode", smode)
        poke("digiwave_pdepth", depth)
        poke("digiwave_sdepth", depth)
        poke("digiwave_speed", speed)
        poke("digiwave_sspeed", speed)
        poke("digiwave_pmix", 127)
        poke("digiwave_mix", 127)
        poke("digiwave_fb", fb)

    set_wave(0, 0)
    s.run_ms(60)
    period = cftiming.measured_period(s.clock, tx) or 166667
    marks = {v: n_run(v) for v in (tx, forced)}

    def slice_all():
        out = []
        for v in (tx, forced):
            r = report(v, marks[v])
            if r:
                out.append(r)
        if not out:
            return None
        return {"worst": max(r["worst"] for r in out),
                "p99": max(r["p99"] for r in out),
                "margin": min(r["margin"] for r in out),
                "late": sum(r["late"] for r in out)}

    def stage(label, **kw):
        set_wave(**kw)
        s.run_ms(a.ms)
        r = slice_all()
        print("%-14s worst %7d  p99 %7d  margin %6.3f  late %d"
              % (label, r["worst"], r["p99"], r["margin"], r["late"]))
        for v in (tx, forced):
            marks[v] = n_run(v)
        return r

    print("period ~%d cycles, %d ms/slice, accel=max" % (period, a.ms))
    base = stage("all-off", page=0, on=0)
    for lab, page, pm, sm, fb in (("WOB", 0, 0, 0, 0), ("SHFT", 0, 96, 0, 0),
                                  ("FLAN", 1, 0, 21, 96), ("PAN", 1, 0, 64, 0),
                                  ("WIDE", 1, 0, 107, 0)):
        w = stage(lab, page=page, on=1, pmode=pm, smode=sm, fb=fb)
        print("  %-5s +%d (margin %.3f)" % (lab, w["worst"] - base["worst"], w["margin"]))
    s.close()
    print("DONE")


if __name__ == "__main__":
    sys.exit(main())
