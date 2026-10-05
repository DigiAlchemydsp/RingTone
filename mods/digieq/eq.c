/* SPDX-License-Identifier: GPL-2.0-or-later
 * digieq: a master tone tilt (low/high band gain) on the output.
 * Digitone mk1 / Keys, OS 1.43.
 *
 * A one-pole split into low and high bands, each with its own gain (Q14 delta
 * from unity). The gains are interpolated across the 32 frames of each block,
 * so a knob move (or a bypass) is a smooth ramp, not a step: no zipper, no
 * click. Bypass ramps both gains to zero, which is passthrough.
 * Subscriptions only: it combines with every mod.
 */
#include "../../src/corea.h"

#ifndef DIGIEQ_CUT
#define DIGIEQ_CUT 4            /* one-pole: lo += (x-lo)>>CUT (~1 kHz) */
#endif

/* runtime parameters (exported; digictl edits them). Low and high have their
 * own enable now, so the page can switch each band independently. */
/* 0..127, centre 64 = flat (stock convention: one step per notch). The DSP
 * scales to the Q14 gain delta: (v - 64) * 128 (v=33 -> -2.2 dB, 111 -> +2.7 dB). */
int digieq_low_on = 1;
int digieq_high_on = 1;
int digieq_low_d = 33;
int digieq_high_d = 111;

static int eq_lo_l, eq_lo_r;
static int eq_low_cur, eq_high_cur;     /* values at the last block's start */
static volatile unsigned eq_off;

void digieq_render_in(void)
{
    eq_off = dn_out_off();
}

void digieq_render_out(void)
{
    int lt = digieq_low_on ? (digieq_low_d - 64) * 128 : 0;   /* 0..127 -> Q14 */
    int ht = digieq_high_on ? (digieq_high_d - 64) * 128 : 0;
    int lstep, hstep, i, lc, hc, lo_l, lo_r;
    int *p;
    if (lt == eq_low_cur && ht == eq_high_cur && lt == 0 && ht == 0)
        return;                                 /* fully bypassed and settled */
    p = (int *)(DN_OUT_BASE + eq_off);
    lstep = (lt - eq_low_cur) >> 5;             /* reach the target over the block */
    hstep = (ht - eq_high_cur) >> 5;
    lc = eq_low_cur;
    hc = eq_high_cur;
    lo_l = eq_lo_l;
    lo_r = eq_lo_r;
    for (i = 0; i < DN_OUT_FRAMES; i++) {
        int l = p[0], r = p[1], hl, hr;
        lo_l += (l - lo_l) >> DIGIEQ_CUT;
        lo_r += (r - lo_r) >> DIGIEQ_CUT;
        hl = l - lo_l;
        hr = r - lo_r;
        /* Full-precision gain (dn_mul14, not dn_q14d): the truncated form
         * quantized the bands in steps of the delta, which is the low-level
         * noise the EQ had. */
        p[0] = l + dn_mul14(lo_l, lc) + dn_mul14(hl, hc);
        p[1] = r + dn_mul14(lo_r, lc) + dn_mul14(hr, hc);
        p += 2;
        lc += lstep;
        hc += hstep;
    }
    eq_low_cur = lt;
    eq_high_cur = ht;
    eq_lo_l = lo_l;
    eq_lo_r = lo_r;
}
