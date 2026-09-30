/* SPDX-License-Identifier: GPL-2.0-or-later
 * digictl: the DIGI FX page on the master page tree (FUNC+LFO), the fourth
 * entry. Enables and tunes digieq / digiring / digifold / digimeter.
 * Digitone mk1 / Keys, OS 1.43.
 *
 * The DN master view (vtable 0x40199BAC) keeps its page kinds in a vector at
 * view+124 (end +128, current index +144); FUNC+LFO cycles it. We insert kind 0
 * as the fourth entry and take over the view's draw (slot 4, 0x40199BBC) while
 * it is shown; every other page calls the stock draw unchanged. The eight
 * encoders edit our parameters through the core ev_enc event, only while our
 * page was the one drawn. The two level bars are drawn here (from digimeter's
 * exported digimeter_l/r) -- the meter is NOT a screen-wide overlay.
 *
 * Encoder steps use the OS's own accumulation: a step once per DC_PER_STEP
 * counts, direction change resets -- so the delta magnitude (the OS's
 * acceleration) is honoured instead of a fixed step per event.
 */
#include "../../src/corea.h"

#define DN_TEXTF      ((void (*)(void *, const void *, int, int, int, const char *, ...))0x400DDE68)
#define DN_FONT5      ((const void *)0x402315C8)
#define DN_INVALIDATE ((void (*)(void *))0x400E512A)
#define DN_OP_NEW     ((int *(*)(unsigned))0x400E944C)
#define DN_STOCK_DRAW ((void (*)(void *, void *))0x4004DDAE)
#define DN_OURKIND    0
#define DC_PER_STEP   16

extern int digieq_on, digieq_low_d, digieq_high_d;
extern int digiring_on, digiring_depth, digiring_freq;
extern int digifold_on, digifold_amount;
extern int digimeter_on, digimeter_l, digimeter_r;

static char *dc_view;
static int dc_visible;
static int dc_eacc[9];              /* per-encoder accumulation, as the OS does */

static int clampi(int v, int lo, int hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

static int cur_kind(char *view)
{
    int *v = *(int **)(view + 124), *e = *(int **)(view + 128), i = *(int *)(view + 144);
    if (!v || i < 0 || i >= e - v)
        return -1;
    return v[i];
}

static void add_page(char *view)
{
    int *v = *(int **)(view + 124), *e = *(int **)(view + 128), *nv;
    int n = e - v, i, j, pos;
    if (!v || n < 1 || n > 15)
        return;
    for (i = 0; i < n; i++)
        if (v[i] == DN_OURKIND)
            return;
    pos = n >= 4 ? 3 : n;                   /* the fourth entry */
    nv = DN_OP_NEW(4u * (unsigned)(n + 1));
    if (!nv)
        return;
    for (i = j = 0; i < n; i++) {
        if (i == pos)
            nv[j++] = DN_OURKIND;
        nv[j++] = v[i];
    }
    if (pos == n)
        nv[j++] = DN_OURKIND;
    *(int **)(view + 124) = nv;
    *(int **)(view + 128) = nv + n + 1;
    *(int **)(view + 132) = nv + n + 1;
}

static void row_on(void *bmp, int y, const char *name, int on)
{
    DN_TEXTF(bmp, DN_FONT5, 1, y, -1, "%s", name);
    DN_TEXTF(bmp, DN_FONT5, 84, y, -1, on ? "ON" : "OFF");
}

static void body(void *bmp)
{
    int hl = (digimeter_l * 4) / 5, hr = (digimeter_r * 4) / 5;
    DN_FILLRECT(bmp, 0, 0, 127, 51, 0);
    row_on(bmp, 48, "EQ", digieq_on);
    DN_TEXTF(bmp, DN_FONT5, 1, 42, -1, "EQ LOW  %d", digieq_low_d);
    DN_TEXTF(bmp, DN_FONT5, 1, 36, -1, "EQ HIGH %d", digieq_high_d);
    row_on(bmp, 30, "RING", digiring_on);
    DN_TEXTF(bmp, DN_FONT5, 1, 24, -1, "RING DEP %d", digiring_depth);
    DN_TEXTF(bmp, DN_FONT5, 1, 18, -1, "RING FRQ %d", digiring_freq);
    row_on(bmp, 12, "FOLD", digifold_on);
    DN_TEXTF(bmp, DN_FONT5, 1, 6, -1, "FOLD AMT %d", digifold_amount);
    /* the level meter, on this page only: two vertical bars on the right */
    DN_FILLRECT(bmp, 112, 0, 115, 48, 0);
    DN_FILLRECT(bmp, 112, 0, 115, hl, 1);
    DN_FILLRECT(bmp, 119, 0, 122, 48, 0);
    DN_FILLRECT(bmp, 119, 0, 122, hr, 1);
}

/* vtable slot 4 of the master view: draw */
void digictl_mdraw(void *view, void *bmp)
{
    add_page((char *)view);
    DN_STOCK_DRAW(view, bmp);
    if (cur_kind((char *)view) == DN_OURKIND) {
        dc_view = (char *)view;
        dc_visible = 1;
        body(bmp);
    }
}

/* every UI frame: keep the page (and its meter) animating while it is shown */
void digictl_tick(void *ctrl)
{
    (void)ctrl;
    if (dc_visible && dc_view && cur_kind(dc_view) == DN_OURKIND)
        DN_INVALIDATE(dc_view);
    dc_visible = 0;
}

/* OS-style step: one step per DC_PER_STEP accumulated counts, reset on turn */
static int dc_steps(int id, int d)
{
    int st;
    if ((d > 0 && dc_eacc[id] < 0) || (d < 0 && dc_eacc[id] > 0))
        dc_eacc[id] = 0;
    dc_eacc[id] += d;
    st = dc_eacc[id] / DC_PER_STEP;
    dc_eacc[id] -= st * DC_PER_STEP;
    return st;
}

int digictl_enc(void *brain, void *ev)
{
    int id = *(int *)((char *)ev + 12);
    int delta = *(int *)((char *)ev + 16);
    int d;
    (void)brain;
    if (!dc_visible || !dc_view || cur_kind(dc_view) != DN_OURKIND)
        return 0;
    if (!delta)
        return 1;
    d = dc_steps(id, delta);
    if (!d)
        return 1;
    switch (id) {
    case 1: digieq_on = (d > 0); break;
    case 2: digieq_low_d = clampi(digieq_low_d + d * 256, -8192, 8192); break;
    case 3: digieq_high_d = clampi(digieq_high_d + d * 256, -8192, 8192); break;
    case 4: digiring_on = (d > 0); break;
    case 5: digiring_depth = clampi(digiring_depth + d * 1024, 0, 32767); break;
    case 6: digiring_freq = clampi(digiring_freq + d * 5, 1, 2000); break;
    case 7: digifold_on = (d > 0); break;
    case 8: digifold_amount = clampi(digifold_amount + d * 16, 0, 1024); break;
    case 9: digimeter_on = (d > 0); break;
    default: break;
    }
    DN_INVALIDATE(dc_view);
    return 1;
}
