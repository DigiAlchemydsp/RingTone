/* SPDX-License-Identifier: GPL-2.0-or-later
 * digiring: a master ring modulator / tremolo insert.
 * Digitone mk1 / Keys, OS 1.43.
 *
 * Multiplies the output by a sine carrier. Depth and carrier frequency are
 * interpolated across each block's 32 frames, so edits and bypass ramp
 * smoothly (no zipper on depth, no pitch step on frequency). Bypass ramps the
 * depth to zero, which is passthrough. Combines with every mod.
 */
#include "../../src/corea.h"
#include "../../src/sin256.h"

/* runtime parameters (exported; digictl edits them) */
int digiring_on = 1;
int digiring_depth = 13107;     /* Q15 wet amount: ~0.40 */
int digiring_freq = 90;         /* carrier Hz: tremolo; raise for a ring */

/* 2^32 / 48000, so inc = freq * DN_RING_K advances an 8-bit-index phase */
#define DN_RING_K 89478

static volatile unsigned di_off;
static unsigned di_phase;
static int di_depth_cur, di_freq_cur;

void digiring_render_in(void)
{
    di_off = dn_out_off();
}

void digiring_render_out(void)
{
    int dt = digiring_on ? digiring_depth : 0;
    int ft = digiring_freq;
    int i, dc, inc, dstep, fstep;
    unsigned ph = di_phase;
    int *p;
    if (dt == di_depth_cur && ft == di_freq_cur && dt == 0)
        return;
    dstep = (dt - di_depth_cur) >> 5;
    fstep = (ft - di_freq_cur) >> 5;
    dc = di_depth_cur;
    inc = di_freq_cur * DN_RING_K;
    p = (int *)(DN_OUT_BASE + di_off);
    for (i = 0; i < DN_OUT_FRAMES; i++) {
        int s = sin256[(ph >> 24) & 0xFFu];
        int l = p[0], r = p[1];
        p[0] = l + dn_q15(dn_q15(l, s) - l, dc);
        p[1] = r + dn_q15(dn_q15(r, s) - r, dc);
        p += 2;
        ph += (unsigned)inc;
        dc += dstep;
        inc += fstep * DN_RING_K;
    }
    di_depth_cur = dt;
    di_freq_cur = ft;
    di_phase = ph;
}
