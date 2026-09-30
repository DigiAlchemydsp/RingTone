/* SPDX-License-Identifier: GPL-2.0-or-later
 * digifold: a master wavefolder.
 * Digitone mk1 / Keys, OS 1.43.
 *
 * A triangle wavefolder: the signal is scaled by (1 + amount) and folded back
 * into [-T, T] (T = 2^22) by reflection, an odd function. amount 0 is 1.0x, so
 * no folding (bypass); higher amounts fold harder and add harmonics. The
 * parameters are globals so digictl's page can edit them.
 *
 * ev_render_in remembers the output half; ev_render_out folds it in place.
 * Subscriptions only: it combines with every mod. Ring -> EQ -> FOLD (the
 * render_out orders set that chain).
 */
#include "../../src/corea.h"

#define DF_T    (1u << 22)          /* fold threshold */
#define DF_2T   (1u << 23)

/* runtime parameters (exported; digictl edits them) */
int digifold_on = 1;
int digifold_amount = 0;            /* 0..1024; gain = (256 + amount)/256 */

static volatile unsigned df_off;

void digifold_render_in(void)
{
    df_off = dn_out_off();
}

static inline int df_fold(int x, unsigned gain)
{
    int s = x < 0 ? -1 : 1;
    unsigned a = x < 0 ? (unsigned)(-x) : (unsigned)x;
    a = (a >> 8) * gain;                /* apply the gain (Q8), in 32 bits */
    a &= (DF_2T - 1u);                  /* |x| mod 2T */
    if (a > DF_T)
        a = DF_2T - a;                  /* reflect into [0, T] */
    return s * (int)a;
}

void digifold_render_out(void)
{
    int *p;
    unsigned gain;
    int i;
    if (!digifold_on)
        return;
    gain = (unsigned)(256 + digifold_amount);
    p = (int *)(DN_OUT_BASE + df_off);
    for (i = 0; i < DN_OUT_FRAMES; i++) {
        p[0] = df_fold(p[0], gain);
        p[1] = df_fold(p[1], gain);
        p += 2;
    }
}
