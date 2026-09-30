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

/* runtime parameters (exported; digictl edits them) */
int digieq_on = 1;
int digieq_low_d = -4000;       /* Q14 low gain-1: -4000 = -2.2 dB */
int digieq_high_d = 6000;       /* Q14 high gain-1: +6000 = +2.7 dB */

static int eq_lo_l, eq_lo_r;
static int eq_low_cur, eq_high_cur;     /* values at the last block's start */
static volatile unsigned eq_off;

void digieq_render_in(void)
{
    eq_off = dn_out_off();
}

void digieq_render_out(void)
{
    int lt = digieq_on ? digieq_low_d : 0;
    int ht = digieq_on ? digieq_high_d : 0;
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
        p[0] = l + dn_q14d(lo_l, lc) + dn_q14d(hl, hc);
        p[1] = r + dn_q14d(lo_r, lc) + dn_q14d(hr, hc);
        p += 2;
        lc += lstep;
        hc += hstep;
    }
    eq_low_cur = lt;
    eq_high_cur = ht;
    eq_lo_l = lo_l;
    eq_lo_r = lo_r;
}
