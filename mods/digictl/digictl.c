/* SPDX-License-Identifier: GPL-2.0-or-later
 * digictl: the master-page UI for the DIGI suite.
 * Digitone mk1 / Keys, OS 1.43.
 *
 * Two pages of our own, appended to the master page tree (view kinds 0, 1),
 * rotated with LEFT / RIGHT while one of them is shown:
 *
 *   DIGI FX      kind 0  RING only: on/off, depth, frequency, meter; a low-CPU
 *                        ring animation and depth/frequency bars on the right
 *   DIGI FOLD/EQ kind 1  FOLD amount (+ spiral), EQ LOW / HIGH faders, each
 *                        with its own on/off encoder
 *
 * None of the stock pages are touched and no stock key or encoder is taken:
 * the pages are only reached by FUNC+LFO (the cycle) or LEFT/RIGHT.
 *
 * The master view (vtable 0x40199BAC) keeps its page kinds in a vector at
 * view+124 (end +128, current index +144). We append kinds 0 and 1 and
 * patch the view's draw (slot 4, 0x40199BBC).
 */
#include "../../src/corea.h"
#include "../../src/sin256.h"

#define DN_TEXTF      ((void (*)(void *, const void *, int, int, int, const char *, ...))0x400DDE68)
#define DN_FONT5      ((const void *)0x402315C8)
#define DN_INVALIDATE ((void (*)(void *))0x400E512A)
#define DN_OP_NEW     ((int *(*)(unsigned))0x400E944C)
#define DN_STOCK_DRAW ((void (*)(void *, void *))0x4004DDAE)
#define DN_FXKIND     0
#define DN_FEKIND     1
#define DN_NPAGES     2
#define DC_PER_STEP   4

extern int digieq_low_on, digieq_high_on, digieq_low_d, digieq_high_d;
extern int digiring_on, digiring_depth, digiring_freq;
extern int digifold_on, digifold_amount;
extern int digimeter_on, digimeter_l, digimeter_r;

/* Track-LFO bridge. A track LFO can target the track's FLTR FREQ; that live
 * value is in the per-voice record at 0x80003544 + (voice-1)*0x9E, FREQ at +0
 * (index<<8, fractional low byte). We read it every block and drive one of our
 * params from it, so a track LFO modulates us. */
int digimod_dest;                    /* 0 off, 1 ring dep, 2 ring frq, 3 fold,
                                        4 EQ low, 5 EQ high.
                                        Parked: no page readout; the DEST/VOICE
                                        encoders still drive it for testing. */
int digimod_voice = 1;               /* 1..8 */
#define DN_FREQ_REC(v) (*(volatile unsigned short *)(0x80003544u + ((v) - 1) * 0x9E))

/* ---- per-pattern storage -----------------------------------------------------
 * Our FX params have no stock field, so they are kept inside the saved pattern.
 * The project's patterns are a 0x1611D-byte struct array at 0x407FC414, one
 * struct per pattern; *0x4138E214 is the current one. The four MIDI tracks each
 * leave a 64-byte block unused at track_t+0x100 (the synth-voice area): it is
 * zero in all 128 slots and the OS's parameter mirror never writes it, but it
 * travels with the pattern. We keep our settings there (pattern + 0x1040), so
 * they follow a pattern switch / reload and survive a project save like stock
 * parameters. `digimod_*` (the LFO bridge) is state, not a sound, and is kept
 * too so a pattern restores the whole page. */
#define DN_PAT_BASE   0x407FC414u
#define DN_PAT_STRIDE 0x1611Du
#define DN_PAT_SLOTS  128u
#define DN_STORE_OFF  0x1040u
#define DN_STORE_N    12
#define DN_STORE_VER  3
#define DN_STORE_MAG(a) ((a)[0] == 0x44 && (a)[1] == 0x47 && \
                         (a)[2] == 0x58 && (a)[3] == 0x31 && \
                         (a)[5] == DN_STORE_VER)               /* "DGX1" v3 */

static int *const dn_fxparam[DN_STORE_N] = {
    &digiring_on, &digiring_depth, &digiring_freq,
    &digieq_low_on, &digieq_high_on, &digieq_low_d, &digieq_high_d,
    &digifold_on, &digifold_amount,
    &digimeter_on, &digimod_dest, &digimod_voice,
};

static unsigned char *dn_store_blk;             /* block we last synced */
static unsigned char dn_store_copy[8 + 2 * DN_STORE_N];
static int dn_store_dirty;                      /* a page edit is pending */

static unsigned char *dn_store_slot(void)
{
    unsigned p = *(volatile unsigned *)0x4138E214u;
    if (p < DN_PAT_BASE ||
        p >= DN_PAT_BASE + (unsigned)DN_PAT_SLOTS * DN_PAT_STRIDE)
        return 0;
    return (unsigned char *)(p + DN_STORE_OFF);
}

static void dn_store_read(const unsigned char *b)
{
    int i;
    for (i = 0; i < DN_STORE_N; i++)
        *dn_fxparam[i] = (short)((b[8 + 2 * i] << 8) | b[9 + 2 * i]);
}

static void dn_store_write(unsigned char *b)
{
    int i;
    b[0] = 0x44; b[1] = 0x47; b[2] = 0x58; b[3] = 0x31;   /* "DGX1" */
    b[4] = 0; b[5] = DN_STORE_VER;                        /* version */
    b[6] = (DN_STORE_N >> 8) & 0xff; b[7] = DN_STORE_N & 0xff;
    for (i = 0; i < DN_STORE_N; i++) {
        int v = *dn_fxparam[i];
        b[8 + 2 * i] = (unsigned char)((v >> 8) & 0xff);
        b[9 + 2 * i] = (unsigned char)(v & 0xff);
    }
}

/* Once a UI frame: follow a pattern switch, persist a page edit, and adopt an
 * external change (a pattern reload) the OS made behind us. */
static void dn_store_sync(void)
{
    unsigned char *b = dn_store_slot();
    int i;
    if (!b)
        return;
    if (b == dn_store_blk) {
        if (dn_store_dirty) {
            dn_store_write(b);
        } else {
            for (i = 0; i < 8 + 2 * DN_STORE_N; i++)
                if (b[i] != dn_store_copy[i])
                    break;
            if (i < 8 + 2 * DN_STORE_N)      /* the OS changed it: adopt */
                dn_store_read(b);
        }
    } else {
        dn_store_blk = b;                    /* pattern switch / first sync */
        if (DN_STORE_MAG(b))
            dn_store_read(b);
        else
            dn_store_write(b);               /* new pattern: adopt live values */
    }
    dn_store_dirty = 0;
    for (i = 0; i < 8 + 2 * DN_STORE_N; i++)
        dn_store_copy[i] = b[i];
}

static int clampi(int v, int lo, int hi);

/* ---- MIDI CC control ---------------------------------------------------------
 * cc_glue.s hooks the incoming CC router (0x400ED94E) and calls this with the
 * CC number and value. Only CC numbers the stock DN table does not use are
 * ours; every other CC falls through to stock untouched. Values are 0..127;
 * on/off params switch at 64. */
#define DN_CC_RING_ON    11
#define DN_CC_RING_DEPTH 8
#define DN_CC_RING_RATE  36
#define DN_CC_FOLD_ON    37
#define DN_CC_FOLD_AMT   40
#define DN_CC_EQ_LO_ON   67
#define DN_CC_EQ_HI_ON   68
#define DN_CC_EQ_LO      69
#define DN_CC_EQ_HI      96

void digictl_cc_apply(int cc, int value)
{
    int v = clampi(value, 0, 127);
    switch (cc) {
    case DN_CC_RING_ON:    digiring_on = (v >= 64); break;
    case DN_CC_RING_DEPTH: digiring_depth = v; break;
    case DN_CC_RING_RATE:  digiring_freq = v; break;
    case DN_CC_FOLD_ON:    digifold_on = (v >= 64); break;
    case DN_CC_FOLD_AMT:   digifold_amount = v; break;
    case DN_CC_EQ_LO_ON:   digieq_low_on = (v >= 64); break;
    case DN_CC_EQ_HI_ON:   digieq_high_on = (v >= 64); break;
    case DN_CC_EQ_LO:      digieq_low_d = v; break;
    case DN_CC_EQ_HI:      digieq_high_d = v; break;
    default: return;                 /* not ours: stock handles/ignores it */
    }
    dn_store_dirty = 1;              /* persist with the pattern */
}

static const int dc_kinds[DN_NPAGES] = { DN_FXKIND, DN_FEKIND };

#define DN_MASTER_VT  0x40199BAC
static char *dc_view;               /* the master view, from its last draw */
static int dc_vis;                  /* frames since the master view was drawn */
static int dc_eacc[9];              /* per-encoder accumulation, as the OS does */

static int clampi(int v, int lo, int hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

/* ev_render_in: apply the track-FLTR-FREQ bridge before the master inserts run
 * (they read the params in this block's ev_render_out), so modulation is a
 * block-rate update, smooth at 1500 Hz. */
void digictl_mod_in(void)
{
    int idx, d = digimod_dest, v = digimod_voice;
    if (v < 1 || v > 8)
        return;
    idx = clampi(DN_FREQ_REC(v) >> 8, 0, 127);
    if (d <= 0)
        return;
    switch (d) {
    case 1: digiring_depth = idx; break;                  /* all 0..127 now */
    case 2: digiring_freq = idx; break;
    case 3: digifold_amount = idx; break;
    case 4: digieq_low_d = idx; break;
    case 5: digieq_high_d = idx; break;
    default: break;
    }
}

/* Alive (its primary vtable is still ours) AND drawn recently: the frame count
 * gives a few frames of grace across the tick/draw gap but stops us once the
 * master page tree is left, so no stock key or encoder is ever taken. */
static int master_live(char *v)
{
    return dc_vis > 0 && v && *(int *)v == DN_MASTER_VT;
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
    if (!v || n < 1 || n > 13)
        return;
    for (i = 0; i < n; i++)
        if (v[i] >= DN_FXKIND && v[i] <= DN_FEKIND)
            return;
    pos = n >= 4 ? 3 : n;                   /* the fourth and fifth */
    nv = DN_OP_NEW(4u * (unsigned)(n + DN_NPAGES));
    if (!nv)
        return;
    for (i = j = 0; i < n; i++) {
        if (i == pos) {
            nv[j++] = DN_FXKIND;
            nv[j++] = DN_FEKIND;
        }
        nv[j++] = v[i];
    }
    if (pos == n) {
        nv[j++] = DN_FXKIND;
        nv[j++] = DN_FEKIND;
    }
    *(int **)(view + 124) = nv;
    *(int **)(view + 128) = nv + n + DN_NPAGES;
    *(int **)(view + 132) = nv + n + DN_NPAGES;
}

/* ---------------- DIGI FX: RING + animation + value/meter bars ---------------- */
static unsigned dg_rng = 0x2545f491u;
static int dg_ang;

static int dg_rand(int m)
{
    dg_rng = dg_rng * 1103515245u + 12345u;
    return (int)((dg_rng >> 16) & 0x7fff) % (m > 0 ? m : 1);
}

static void dg_ring(void *bmp)
{
    int cx = 40, cy = 32, R = 17, i, n = 24;
    int dep = digiring_on ? digiring_depth * 258 : 0;   /* 0..127 -> Q15 */
    for (i = 0; i < n; i++) {
        int a = (i * 256 / n) & 0xff;
        int s = sin256[a], c = sin256[(a + 64) & 0xff];
        int x = cx + ((c * R) >> 15), y = cy + ((s * R) >> 15);
        DN_FILLRECT(bmp, x, y, x, y, 1);
    }
    if (dep > 0) {
        int s = sin256[dg_ang & 0xff], c = sin256[(dg_ang + 64) & 0xff];
        int amp = (dep * 14) >> 15;
        int jx = dg_rand(2 * amp + 1) - amp, jy = dg_rand(2 * amp + 1) - amp;
        int x = cx + ((c * R) >> 15) + jx, y = cy + ((s * R) >> 15) + jy;
        DN_FILLRECT(bmp, x - 1, y - 1, x + 1, y + 1, 1);
        dg_ang = (dg_ang + (digiring_freq / 8 + 1)) & 0xff;
    }
}

static void dg_vbar(void *bmp, int x0, int x1, int num, int den)
{
    int h = 48, f;
    if (den <= 0)
        return;
    f = num * h / den;
    if (f < 0) f = 0;
    if (f > h) f = h;
    DN_FILLRECT(bmp, x0, 6, x1, 6 + h, 0);
    DN_FILLRECT(bmp, x0, 6, x1, 6 + f, 1);
}

static void dg_fx_page(void *bmp)
{
    DN_FILLRECT(bmp, 0, 0, 127, 63, 0);
    DN_TEXTF(bmp, DN_FONT5, 1, 58, -1, "DIGI FX");
    DN_TEXTF(bmp, DN_FONT5, 56, 58, -1, "RING %s", digiring_on ? "ON" : "OFF");
    dg_ring(bmp);
    DN_TEXTF(bmp, DN_FONT5, 1, 8, -1, "DEP %d", digiring_depth);
    DN_TEXTF(bmp, DN_FONT5, 46, 8, -1, "FRQ %d", digiring_freq);
    DN_TEXTF(bmp, DN_FONT5, 1, 0, -1, "LEFT/RIGHT = PAGES");
    dg_vbar(bmp, 104, 106, digiring_on ? digiring_depth : 0, 127);
    dg_vbar(bmp, 109, 111, digiring_freq, 127);
    dg_vbar(bmp, 118, 120, digimeter_l, 60);
    dg_vbar(bmp, 123, 125, digimeter_r, 60);
}

/* ---------------- DIGI FOLD / EQ: spiral + faders ---------------- */

/* the fold amount as a spiral: a straight line at 0, coiling as it folds */
static void dg_spiral(void *bmp, int amount)
{
    int cx = 24, cy = 28, i, n = 44, turns, rmax;
    if (amount <= 0) {                  /* straight when not folding */
        DN_FILLRECT(bmp, cx - 16, cy, cx + 16, cy, 1);
        return;
    }
    turns = 1 + amount * 3 / 128;       /* 1..3 turns */
    rmax = 7 + amount * 9 / 128;        /* 7..16 radius */
    for (i = 0; i < n; i++) {
        int t = i * 256 * turns / n;
        int r = 3 + (rmax - 3) * i / n;
        int a = t & 0xff;
        int s = sin256[a], c = sin256[(a + 64) & 0xff];
        int x = cx + ((c * r) >> 15), y = cy + ((s * r) >> 15);
        DN_FILLRECT(bmp, x, y, x, y, 1);
    }
}

/* a fader: a body; filled to the value when the band is on, empty when off */
static void dg_fader(void *bmp, int x, int on, int val, int vmin, int vmax,
                     const char *name)
{
    int y0 = 8, y1 = 44, pos;
    DN_FRAMERECT(bmp, x - 3, y0 - 1, x + 3, y1 + 1, 1);
    if (on) {                           /* on: the body fills to the value */
        val = clampi(val, vmin, vmax);
        pos = y0 + (val - vmin) * (y1 - y0) / (vmax - vmin);
        DN_FILLRECT(bmp, x - 2, y0, x + 2, pos, 1);
    }
    DN_TEXTF(bmp, DN_FONT5, x - 6, 1, -1, "%s", name);
}

static void dg_fe_page(void *bmp)
{
    DN_FILLRECT(bmp, 0, 0, 127, 63, 0);
    DN_TEXTF(bmp, DN_FONT5, 1, 58, -1, "DIGI FOLD / EQ");
    dg_spiral(bmp, digifold_on ? digifold_amount : 0);   /* fold amount */
    dg_fader(bmp, 60, digifold_on, digifold_amount, 0, 127, "FOLD");
    dg_fader(bmp, 84, digieq_low_on, digieq_low_d, 0, 127, "LOW");
    dg_fader(bmp, 108, digieq_high_on, digieq_high_d, 0, 127, "HIGH");
}

/* vtable slot 4 of the master view: draw */
void digictl_mdraw(void *view, void *bmp)
{
    int k;
    add_page((char *)view);
    DN_STOCK_DRAW(view, bmp);
    dc_view = (char *)view;
    dc_vis = 4;
    k = cur_kind(dc_view);
    if (k == DN_FXKIND)
        dg_fx_page(bmp);
    else if (k == DN_FEKIND)
        dg_fe_page(bmp);
}

/* every UI frame: keep our animated pages redrawing while shown */
void digictl_tick(void *ctrl)
{
    int k;
    (void)ctrl;
    dn_store_sync();
    if (dc_vis)
        dc_vis--;
    if (dc_vis > 0 && dc_view) {
        k = cur_kind(dc_view);
        if (k == DN_FXKIND || k == DN_FEKIND)
            DN_INVALIDATE(dc_view);
    }
}

/* Stock convention: every parameter is 0..127, so one step is one unit. The
 * Digitone panel sends 4 wire counts per encoder detent and the stock 0..127
 * params move one step per detent (see digiemu's devices/digitone.toml), so one
 * step is 4 counts. The event delta is the accumulated wire count, clamped to
 * +/-30 by the encoder driver, so a fast turn naturally gives more steps. */

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
    int k, d;
    (void)brain;
    if (!master_live(dc_view))
        return 0;
    k = cur_kind(dc_view);

    if (k == DN_FEKIND) {
        if (!delta)
            return 1;
        d = dc_steps(id, delta);
        if (!d)
            return 1;
        switch (id) {
        case 1: digifold_on = (d > 0); break;
        case 2: digifold_amount = clampi(digifold_amount + d, 0, 127); break;
        case 3: digieq_low_on = (d > 0); break;
        case 4: digieq_low_d = clampi(digieq_low_d + d, 0, 127); break;
        case 5: digieq_high_on = (d > 0); break;
        case 6: digieq_high_d = clampi(digieq_high_d + d, 0, 127); break;
        case 7: digimod_dest = clampi(digimod_dest + (d > 0 ? 1 : -1), 0, 5); break;
        case 8: digimod_voice = clampi(digimod_voice + (d > 0 ? 1 : -1), 1, 8); break;
        case 9: digimeter_on = (d > 0); break;
        default: break;
        }
        dn_store_dirty = 1;
        DN_INVALIDATE(dc_view);
        return 1;
    }
    if (k != DN_FXKIND)
        return 0;
    if (!delta)
        return 1;
    d = dc_steps(id, delta);
    if (!d)
        return 1;
    switch (id) {
    case 1: digiring_on = (d > 0); break;
    case 2: digiring_depth = clampi(digiring_depth + d, 0, 127); break;
    case 3: digiring_freq = clampi(digiring_freq + d, 0, 127); break;
    case 9: digimeter_on = (d > 0); break;
    default: break;
    }
    dn_store_dirty = 1;
    DN_INVALIDATE(dc_view);
    return 1;
}

/* the vector index of a page kind, or -1 */
static int kind_index(char *view, int kind)
{
    int *v = *(int **)(view + 124), *e = *(int **)(view + 128), i;
    for (i = 0; v && i < e - v; i++)
        if (v[i] == kind)
            return i;
    return -1;
}

/* LEFT / RIGHT rotate our two pages (DIGI FX <-> DIGI FOLD/EQ).
 * No stock key is taken. */
int digictl_key(void *brain, void *ev)
{
    int id = *(int *)((char *)ev + 12);
    int flags = *(int *)((char *)ev + 16);
    int k, i, cur = 0, idx;
    (void)brain;
    if (!master_live(dc_view))
        return 0;
    if (!(flags & 1) || (flags & 0x10) || (flags & 8))
        return 0;                               /* ignore key-repeat */
    k = cur_kind(dc_view);
    if (k != DN_FXKIND && k != DN_FEKIND)
        return 0;
    if (id == 17 || id == 18) {                 /* LEFT / RIGHT: rotate pages */
        for (i = 0; i < DN_NPAGES; i++)
            if (dc_kinds[i] == k)
                cur = i;
        cur = (cur + (id == 18 ? 1 : DN_NPAGES - 1)) % DN_NPAGES;
        idx = kind_index(dc_view, dc_kinds[cur]);
        if (idx >= 0) {
            *(int *)(dc_view + 144) = idx;
            DN_INVALIDATE(dc_view);
            return 1;
        }
        return 0;
    }
    return 0;
}
