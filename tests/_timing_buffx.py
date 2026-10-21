#!/usr/bin/env python3
"""Bounded cftiming margin probe for the buffer-FX engines (one Session, sliced).

Boots the settled snapshot once, then enables each engine in turn and reports the
audio render margin (1 - worst/period) over a slice of runs, so the per-engine
cost and the all-on worst case are measured on the same clock. Needs the
patched-Unicorn python (digiemu venv).

    python tests/_timing_buffx.py --fw dn1-0.2w-f6736c1e \
        --map testout/tonefx-buffx-1.43.syx.map.json --ms 120
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
        worst = sw[-1]
        p99 = sw[min(len(sw) - 1, int(len(sw) * 0.99))]
        return {"n": len(w), "worst": worst, "p99": p99,
                "mean": round(sum(w) / len(w), 1),
                "margin": round(1 - worst / period, 4),
                "late": sum(1 for x in w if x > period)}

    def set_engines(mode=0, on=0):
        poke("digiwrmz_mode", mode)
        poke("digiwrmz_on", on if mode == 0 else 0)
        poke("digigrainz_on", on if mode == 1 else 0)
        poke("digiwrmz_mix", 127); poke("digiwrmz_fb", 60)
        poke("digigrainz_mix", 127); poke("digigrainz_dens", 110)
        poke("digigrainz_fb", 60)

    # warm (stock render, FX off), then mark the counters
    set_engines()
    s.run_ms(60)
    period = cftiming.measured_period(s.clock, tx) or 0
    if period <= 0:
        period = 166667                      # 667 us block at 250 MHz
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
                "mean": max(r["mean"] for r in out),
                "margin": min(r["margin"] for r in out),
                "late": sum(r["late"] for r in out)}

    def stage(label, **kw):
        set_engines(**kw)
        s.run_ms(a.ms)
        r = slice_all()
        print("%-14s worst %7d  p99 %7d  mean %7.0f  margin %6.3f  late %d"
              % (label, r["worst"], r["p99"], r["mean"], r["margin"], r["late"]))
        for v in (tx, forced):
            marks[v] = n_run(v)
        return r

    print("period ~%d cycles, %d ms/slice, accel=max" % (period, a.ms))
    base = stage("all-off")
    w = stage("WRMZ", mode=0, on=1)
    g = stage("GRAINZ", mode=1, on=1)

    print("\nper-mode cost (worst cycles over baseline):")
    print("  WRMZ   +%d (margin %.3f)" % (w["worst"] - base["worst"], w["margin"]))
    print("  GRAINZ +%d (margin %.3f)" % (g["worst"] - base["worst"], g["margin"]))
    s.close()
    print("DONE")


if __name__ == "__main__":
    sys.exit(main())
