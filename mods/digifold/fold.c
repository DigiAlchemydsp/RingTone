/* SPDX-License-Identifier: GPL-2.0-or-later
 * digifold: a master wavefolder with a continuous fold "type".
 * Digitone mk1 / Keys, OS 1.43.
 *
 * A triangle wavefolder: the signal is scaled by a gain and folded back into
 * [-T, T] (T = 2^22) by reflection, an odd function. amount 0 is 1.0x, so no
 * folding (bypass); higher amounts fold harder and add harmonics.
 *
 * The fold TYPE is a continuous 0..127 knob spread over four modes:
 *   CLEAN  fold only, 36% range       MUD  fold only, full range
 *   DIST   fold 36% + hard-clip OD    TRSH fold full + hard-clip OD
 * The mode scales the fold gain and (for the DIST/TRSH half) the overdrive,
 * interpolated between adjacent modes so the selection is smooth, and capped
 * at CLEAN (min) and TRSH (max). The overdrive is a stateless gain-into-clamp
 * (one Q8 multiply + two compares per sample), the cheapest saturation.
 *
 * ev_render_in remembers the output half; ev_render_out folds it in place.
 * Subscriptions only: it combines with every mod. Ring -> EQ -> FOLD.
 */
#include "../../src/corea.h"

#define DF_T    (1u << 22)          /* fold threshold / clip ceiling */
#define DF_2T   (1u << 23)

/* runtime parameters (exported; digictl edits them).
 * Stock convention: 0..127, one step per notch. */
int digifold_on = 1;
int digifold_amount = 0;            /* 0..127 */
int digifold_mode = 48;            /* 0..127 fold type (CLEAN..TRSH) */

static volatile unsigned df_off;

void digifold_render_in(void)
{
    df_off = dn_out_off();
}

/* the four modes, as percentages (fold range, overdrive) */
static const int df_foldpct[4] = { 36, 100, 36, 100 };
static const int df_drvpct[4]  = {  0,   0, 100, 100 };

/* interpolate the mode percentages at the current fold type */
static void df_mode(int *foldpct, int *drvpct)
{
    int p = digifold_mode * 3;          /* 0..381 -> 0..3 over the range */
    int b = p / 127;                    /* 0..3 */
    int r = p - b * 127;                /* 0..126 */
    int nb = b < 3 ? b + 1 : 3;
    *foldpct = df_foldpct[b] + (df_foldpct[nb] - df_foldpct[b]) * r / 127;
    *drvpct  = df_drvpct[b]  + (df_drvpct[nb]  - df_drvpct[b])  * r / 127;
}

/* fold gain (Q8: 256 = 1.0x) for the current mode */
static unsigned df_gain(int foldpct)
{
    return 256u + (unsigned)(digifold_amount * 8 * foldpct) / 100u;
}

/* overdrive drive gain (Q8): 1.0x .. ~4.0x, 0 = no overdrive */
static unsigned df_drive_gain(int drvpct)
{
    if (drvpct <= 0)
        return 0u;
    return 256u + (unsigned)(digifold_amount * 6 * drvpct) / 100u;
}

static inline int df_fold(int x, unsigned gain)
{
    int s = x < 0 ? -1 : 1;
    unsigned a = x < 0 ? (unsigned)(-x) : (unsigned)x;
    /* full-precision Q8 gain: the truncated form zeroed the low 8 bits even at
     * amount 0, which was noise; amount 0 is now bypassed entirely below. */
    a = (a >> 8) * gain + (((a & 0xffu) * gain) >> 8);
    a &= (DF_2T - 1u);                  /* |x| mod 2T */
    if (a > DF_T)
        a = DF_2T - a;                  /* reflect into [0, T] */
    return s * (int)a;
}

/* hard-clip overdrive: a Q8 gain into a clamp at +/-T (odd, stateless) */
static inline int df_drive(int x, unsigned g)
{
    int y = (x >> 8) * g + (((x & 0xffu) * g) >> 8);
    if (y > (int)DF_T)
        return (int)DF_T;
    if (y < -(int)DF_T)
        return -(int)DF_T;
    return y;
}

void digifold_render_out(void)
{
    int *p;
    unsigned gain, dg;
    int i, fp, dp;
    if (!digifold_on || digifold_amount == 0)
        return;                         /* amount 0 is exact bypass */
    df_mode(&fp, &dp);
    gain = df_gain(fp);
    dg = df_drive_gain(dp);
    p = (int *)(DN_OUT_BASE + df_off);
    for (i = 0; i < DN_OUT_FRAMES; i++) {
        p[0] = df_fold(p[0], gain);
        p[1] = df_fold(p[1], gain);
        if (dg) {
            p[0] = df_drive(p[0], dg);
            p[1] = df_drive(p[1], dg);
        }
        p += 2;
    }
}
