#!/usr/bin/env python3
"""Floating-point reference for Digi Filter's (Digitone port) SVF modes.

The target DSP (mods/digifilter/filter_dsp.s) is the trapezoidal state-variable
filter: v1 is the band, v2 the low, and a mode is an output mix (m0, m1, m2)
over (v0, v1, v2). This model is what the fixed-point coefficients in
mods/digifilter/filter.c are checked against.

    python tests/filter_model.py     # self-test: the mix matches the analytic |H|

Modes: BP = band-pass, mix (0, k, 0); BP2 is the same mix at ~half the Q (a
wider band, k from K27[qi>>1]). COMB/TRASH are feedback combs (not SVF mixes)
and use `comb_gain`. with k = 1/Q. H_lp = 1/D, H_bp = s/D,
D = s^2 + k*s + 1, so H_BP = k*H_bp.
"""
import cmath
import math

MODES = {"BP": (0.0, 1.0, 0.0)}             # BP2 is the same mix at a lower Q


def mix(mode, k):
    """-> the (m0, m1, m2) of `mode` at 1/Q = k (m1 carries the k)."""
    m0, m1, m2 = MODES[mode]
    return m0, m1 * k, m2


def h_analytic(mode, f, fs, q):
    """|H(e^{jw})| of `mode` by the analog prototype (s = j w/w0, prewarped)."""
    k = 1.0 / q
    w0 = 2.0 * math.pi * f / fs
    s = 1j * math.tan(math.pi * f / fs) / math.tan(math.pi * w0 / (2 * math.pi))
    d = s * s + k * s + 1.0
    m0, m1, m2 = mix(mode, k)
    h = m0 + m1 * (s / d) + m2 * (1.0 / d)
    return abs(h)


def comb_gain(f, fs, d, g):
    """|H| of the feedback comb y = x + g*y[n-D] at frequency f."""
    z = cmath.exp(-2j * math.pi * f / fs)
    return abs(1.0 / (1.0 - g * z ** d))


def svf_block(mode, x, fs, fc, q):
    """Run the model's sample loop -> the output list (matches the target DSP)."""
    k = 1.0 / q
    g = math.tan(math.pi * fc / fs)
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    m0, m1, m2 = mix(mode, k)
    ic1 = ic2 = 0.0
    out = []
    for v0 in x:
        v3 = v0 - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        out.append(m0 * v0 + m1 * v1 + m2 * v2)
    return out


def _selftest():
    fs = 48000.0
    fc, q = 1000.0, 0.707
    for mode in MODES:
        want = h_analytic(mode, fc, fs, q)
        n = 4000
        x = [math.sin(2.0 * math.pi * fc * i / fs) for i in range(n)]
        y = svf_block(mode, x, fs, fc, q)
        amp = max(abs(v) for v in y[n // 2:])
        err = abs(amp - want)
        print("%-6s |H(fc)| model=%.4f  svf=%.4f  err=%.4f" % (mode, want, amp, err))
        assert err < 0.05, (mode, want, amp)
    # a comb at its peak frequency: g = 0.9, D = 48 -> peak gain 1/(1-g)
    g = 0.9
    peak = comb_gain(0.0, fs, 48, g)
    print("COMB   peak model=%.4f  analytic=%.4f" % (peak, 1.0 / (1.0 - g)))
    assert abs(peak - 1.0 / (1.0 - g)) < 1e-6
    print("filter_model: OK")


if __name__ == "__main__":
    _selftest()
