/* SPDX-License-Identifier: GPL-2.0-or-later
 * digictl: the master-page UI for the DIGI suite.
 * Digitone mk1 / Keys, OS 1.43.
 *
 * Three pages of our own, appended to the master page tree (view kinds 0, 1, 2),
 * rotated with LEFT / RIGHT (or the on-screen < > arrows):
 *
 *   RING  kind 0  E = depth, F = frequency; a centred ring animation, the
 *                 depth/frequency bars on the right and the values bottom-right
 *   FOLD  kind 1  A = on/off, D = fold type (CLEAN/MUD/DIST/TRSH, continuous),
 *                 E/F/G/H = amount; the spiral on the left, the big mode title
 *                 centred, the amount as a vertical slider next to the meter
 *   TILT  kind 2  A = on/off, E = low shelf, H = high shelf; a bent response
 *
 * The stock top status bar (rows 53..63) is left untouched; our drawing stays
 * below it. None of the stock pages are taken: the pages are reached by FUNC+LFO
 * or LEFT/RIGHT.
 *
 * The master view (vtable 0x40199BAC) keeps its page kinds in a vector at
 * view+124 (end +128, current index +144). We append kinds 0, 1 and 2 and patch
 * the view's draw (slot 4, 0x40199BBC).
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
#define DN_EQKIND     2
#define DN_NPAGES     3
#define DC_PER_STEP   4
#define DG_TOP        53            /* rows 53..63 are the stock status bar */

/* the stock 5-px font tables (glyph widths, bitmap offsets, bitmap bytes) */
#define DN_FW  ((const unsigned char *)0x402315DC)
#define DN_FO  ((const unsigned short *)0x402316DC)
#define DN_FB  ((const unsigned char *)0x402318DC)

extern int digieq_on, digieq_lo, digieq_hi;
extern int digiring_on, digiring_depth, digiring_freq;
extern int digifold_on, digifold_amount, digifold_mode;
extern int digimeter_on, digimeter_l, digimeter_r;

/* Track-LFO bridge. A track LFO can target the track's FLTR FREQ; that live
 * value is in the per-voice record at 0x80003544 + (voice-1)*0x9E, FREQ at +0
 * (index<<8, fractional low byte). We read it every block and drive one of our
 * params from it, so a track LFO modulates us. */
int digimod_dest;                    /* 0 off, 1 ring dep, 2 ring frq, 3 fold,
                                        4 EQ low, 5 EQ high.
                                        Parked: no page readout. */
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
 * parameters. */
#define DN_PAT_BASE   0x407FC414u
#define DN_PAT_STRIDE 0x1611Du
#define DN_PAT_SLOTS  128u
#define DN_STORE_OFF  0x1040u
#define DN_STORE_N    12
#define DN_STORE_VER  5
#define DN_STORE_MAG(a) ((a)[0] == 0x44 && (a)[1] == 0x47 && \
                         (a)[2] == 0x58 && (a)[3] == 0x31 && \
                         (a)[5] == DN_STORE_VER)               /* "DGX1" v5 */

static int *const dn_fxparam[DN_STORE_N] = {
    &digiring_on, &digiring_depth, &digiring_freq,
    &digieq_on, &digieq_lo, &digieq_hi,
    &digifold_on, &digifold_amount, &digifold_mode,
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
#define DN_CC_FOLD_MODE  41
#define DN_CC_EQ_ON      67
#define DN_CC_EQ_LO      69
#define DN_CC_EQ_HI      96
#define DN_CC_METER_ON   68

void digictl_cc_apply(int cc, int value)
{
    int v = clampi(value, 0, 127);
    switch (cc) {
    case DN_CC_RING_ON:    digiring_on = (v >= 64); break;
    case DN_CC_RING_DEPTH: digiring_depth = v; break;
    case DN_CC_RING_RATE:  digiring_freq = v; break;
    case DN_CC_FOLD_ON:    digifold_on = (v >= 64); break;
    case DN_CC_FOLD_AMT:   digifold_amount = v; break;
    case DN_CC_FOLD_MODE:  digifold_mode = v; break;
    case DN_CC_EQ_ON:      digieq_on = (v >= 64); break;
    case DN_CC_EQ_LO:      digieq_lo = v; break;
    case DN_CC_EQ_HI:      digieq_hi = v; break;
    case DN_CC_METER_ON:   digimeter_on = (v >= 64); break;
    default: return;                 /* not ours: stock handles/ignores it */
    }
    dn_store_dirty = 1;              /* persist with the pattern */
}

static const int dc_kinds[DN_NPAGES] = { DN_FXKIND, DN_FEKIND, DN_EQKIND };

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
    if (v < 1 || v > 8 || d <= 0)
        return;
    idx = clampi(DN_FREQ_REC(v) >> 8, 0, 127);
    switch (d) {
    case 1: digiring_depth = idx; break;
    case 2: digiring_freq = idx; break;
    case 3: digifold_amount = idx; break;
    case 4: digieq_lo = idx; break;
    case 5: digieq_hi = idx; break;
    default: break;
    }
}

/* Alive (its primary vtable is still ours) AND drawn recently. */
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
        if (v[i] >= DN_FXKIND && v[i] <= DN_EQKIND)
            return;
    pos = n >= 4 ? 3 : n;                   /* after the stock master pages */
    nv = DN_OP_NEW(4u * (unsigned)(n + DN_NPAGES));
    if (!nv)
        return;
    for (i = j = 0; i < n; i++) {
        if (i == pos) {
            nv[j++] = DN_FXKIND;
            nv[j++] = DN_FEKIND;
            nv[j++] = DN_EQKIND;
        }
        nv[j++] = v[i];
    }
    if (pos == n) {
        nv[j++] = DN_FXKIND;
        nv[j++] = DN_FEKIND;
        nv[j++] = DN_EQKIND;
    }
    *(int **)(view + 124) = nv;
    *(int **)(view + 128) = nv + n + DN_NPAGES;
    *(int **)(view + 132) = nv + n + DN_NPAGES;
    if (*(int *)(view + 144) >= n + DN_NPAGES)
        *(int *)(view + 144) = 0;
}

/* ---------------- small text helpers (stock 5-px font, optional 2x) ---------- */
static int dg_strw(const char *s, int sc)
{
    int w = 0;
    for (; *s; s++)
        w += (DN_FW[(unsigned char)*s] + 1) * sc;
    return w;
}

static void dg_glyph(void *bmp, int x, int ytop, int ch, int sc)
{
    int w = DN_FW[ch & 0xff];
    int off = DN_FO[ch & 0xff];
    int c, r;
    for (c = 0; c < w; c++) {
        int bits = DN_FB[off + c];
        for (r = 0; r < 8; r++) {
            if (bits & (1 << r)) {              /* bit 0 = top of the glyph */
                int px = x + c * sc;
                int py = ytop - r * sc;
                DN_FILLRECT(bmp, px, py, px + sc - 1, py - sc + 1, 1);
            }
        }
    }
}

static void dg_text(void *bmp, int x, int ytop, const char *s, int sc)
{
    for (; *s; s++) {
        dg_glyph(bmp, x, ytop, (unsigned char)*s, sc);
        x += (DN_FW[(unsigned char)*s] + 1) * sc;
    }
}

/* the page title, centred in the bottom third */
static void dg_title(void *bmp, const char *s)
{
    DN_TEXTF(bmp, DN_FONT5, (128 - dg_strw(s, 1)) / 2, 12, -1, "%s", s);
}

/* the little < > page arrows, centred vertically on each side */
static void dg_arrows(void *bmp)
{
    dg_glyph(bmp, 3, 30, '<', 1);
    dg_glyph(bmp, 122, 30, '>', 1);
}

/* ---------------- RING: animation + value bars ---------------- */
static unsigned dg_rng = 0x2545f491u;
static int dg_ang;

static int dg_rand(int m)
{
    dg_rng = dg_rng * 1103515245u + 12345u;
    return (int)((dg_rng >> 16) & 0x7fff) % (m > 0 ? m : 1);
}

static void dg_ring(void *bmp)
{
    int cx = 60, cy = 35, R = 14, i, n = 24;
    int dep = digiring_on ? digiring_depth * 258 : 0;   /* 0..127 -> Q15 */
    for (i = 0; i < n; i++) {
        int a = (i * 256 / n) & 0xff;
        int s = sin256[a], c = sin256[(a + 64) & 0xff];
        int x = cx + ((c * R) >> 15), y = cy + ((s * R) >> 15);
        DN_FILLRECT(bmp, x, y, x, y, 1);
    }
    if (dep > 0) {
        int s = sin256[dg_ang & 0xff], c = sin256[(dg_ang + 64) & 0xff];
        int amp = (dep * 13) >> 15;
        int jx = dg_rand(2 * amp + 1) - amp, jy = dg_rand(2 * amp + 1) - amp;
        int x = cx + ((c * R) >> 15) + jx, y = cy + ((s * R) >> 15) + jy;
        DN_FILLRECT(bmp, x - 1, y - 1, x + 1, y + 1, 1);
        dg_ang = (dg_ang + (digiring_freq / 8 + 1)) & 0xff;
    }
}

static void dg_vbar(void *bmp, int x0, int x1, int num, int den)
{
    int h = 42, y0 = 8, f;
    if (den <= 0)
        return;
    f = num * h / den;
    if (f < 0) f = 0;
    if (f > h) f = h;
    DN_FILLRECT(bmp, x0, y0, x1, y0 + h, 0);
    DN_FILLRECT(bmp, x0, y0, x1, y0 + f, 1);
}

static void dg_fx_page(void *bmp)
{
    DN_FILLRECT(bmp, 0, 0, 127, DG_TOP - 1, 0);
    dg_arrows(bmp);
    dg_ring(bmp);
    dg_vbar(bmp, 104, 106, digiring_on ? digiring_depth : 0, 127);
    dg_vbar(bmp, 110, 112, digiring_freq, 127);
    DN_TEXTF(bmp, DN_FONT5, 2, 4, -1, "DEP %d FRQ %d", digiring_depth, digiring_freq);
    dg_title(bmp, "RING");
}

/* ---------------- FOLD: spiral + big mode + amount slider + meter ------------ */

/* the fold amount as a spiral: a straight line at 0, coiling as it folds */
static void dg_spiral(void *bmp, int amount)
{
    int cx = 20, cy = 30, i, n = 44, turns, rmax;
    if (amount <= 0) {                  /* straight when not folding */
        DN_FILLRECT(bmp, cx - 14, cy, cx + 14, cy, 1);
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

static const char *dg_modename(int m)
{
    static const char *const n[4] = { "CLEAN", "MUD", "DIST", "TRSH" };
    return n[m & 3];
}

static void dg_slider(void *bmp, int x, int val, int vmax)
{
    int y0 = 10, y1 = 44, pos;
    DN_FRAMERECT(bmp, x - 2, y0 - 1, x + 2, y1 + 1, 1);
    val = clampi(val, 0, vmax);
    pos = y0 + val * (y1 - y0) / vmax;
    DN_FILLRECT(bmp, x - 1, y0, x + 1, pos, 1);
}

static void dg_fold_page(void *bmp)
{
    int band = digifold_mode / 32;
    const char *m;
    DN_FILLRECT(bmp, 0, 0, 127, DG_TOP - 1, 0);
    dg_arrows(bmp);
    dg_spiral(bmp, digifold_on ? digifold_amount : 0);   /* left */
    if (band > 3) band = 3;
    m = dg_modename(band);
    dg_text(bmp, (128 - dg_strw(m, 2)) / 2, 36, m, 2);   /* big, centred */
    dg_slider(bmp, 94, digifold_on ? digifold_amount : 0, 127);
    dg_vbar(bmp, 106, 108, digimeter_l, 60);
    dg_vbar(bmp, 113, 115, digimeter_r, 60);
    DN_TEXTF(bmp, DN_FONT5, 89, 3, -1, "%d", digifold_amount);
    dg_title(bmp, "FOLD");
}

/* ---------------- TILT: a bent low/high shelf curve ---------------- */

static int dg_eq_y(int x)
{
    int lo = 30 + (digieq_lo - 64) / 3;
    int hi = 30 + (digieq_hi - 64) / 3;
    int y;
    if (!digieq_on)
        return 30;
    if (x < 24)
        y = lo;
    else if (x < 48)
        y = lo + (30 - lo) * (x - 24) / 24;
    else if (x < 80)
        y = 30;
    else if (x < 104)
        y = 30 + (hi - 30) * (x - 80) / 24;
    else
        y = hi;
    return clampi(y, 8, 50);
}

static void dg_eq_page(void *bmp)
{
    int x;
    DN_FILLRECT(bmp, 0, 0, 127, DG_TOP - 1, 0);
    dg_arrows(bmp);
    for (x = 8; x <= 120; x += 2)           /* 0 dB reference */
        DN_FILLRECT(bmp, x, 30, x, 30, 1);
    for (x = 8; x <= 120; x++)
        DN_FILLRECT(bmp, x, dg_eq_y(x), x, dg_eq_y(x), 1);
    DN_TEXTF(bmp, DN_FONT5, 4, 6, -1, "LO %d", digieq_lo);
    DN_TEXTF(bmp, DN_FONT5, 96, 6, -1, "HI %d", digieq_hi);
    dg_title(bmp, "TILT");
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
        dg_fold_page(bmp);
    else if (k == DN_EQKIND)
        dg_eq_page(bmp);
}

/* every UI frame: keep the master view redrawing while it is shown, so the
 * animation, the meter and LEFT/RIGHT navigation always keep working */
void digictl_tick(void *ctrl)
{
    (void)ctrl;
    dn_store_sync();
    if (dc_vis)
        dc_vis--;
    if (dc_vis > 0 && dc_view && *(int *)dc_view == DN_MASTER_VT)
        DN_INVALIDATE(dc_view);
}

/* Stock convention: every parameter is 0..127, so one step is one unit. The
 * Digitone panel sends 4 wire counts per encoder detent and the stock 0..127
 * params move one step per detent, so one step is 4 counts. */
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
    if (k != DN_FXKIND && k != DN_FEKIND && k != DN_EQKIND)
        return 0;
    if (!delta)
        return 1;
    d = dc_steps(id, delta);
    if (!d)
        return 1;

    if (k == DN_FEKIND) {
        switch (id) {
        case 1: digifold_on = (d > 0); break;
        case 4: digifold_mode = clampi(digifold_mode + d, 0, 127); break;
        case 5: case 6: case 7: case 8:     /* E/F/G/H all edit the amount */
            digifold_amount = clampi(digifold_amount + d, 0, 127); break;
        case 9: digimeter_on = (d > 0); break;
        default: break;
        }
    } else if (k == DN_EQKIND) {
        switch (id) {
        case 1: digieq_on = (d > 0); break;
        case 5: digieq_lo = clampi(digieq_lo + d, 0, 127); break;
        case 8: digieq_hi = clampi(digieq_hi + d, 0, 127); break;
        default: break;
        }
    } else {                             /* DN_FXKIND */
        switch (id) {
        case 1: digiring_on = (d > 0); break;
        case 5: digiring_depth = clampi(digiring_depth + d, 0, 127); break;
        case 6: digiring_freq = clampi(digiring_freq + d, 0, 127); break;
        case 9: digimeter_on = (d > 0); break;
        default: break;
        }
    }
    dn_store_dirty = 1;
    DN_INVALIDATE(dc_view);
    return 1;
}

/* LEFT / RIGHT rotate the whole master page vector (stock pages included). */
int digictl_key(void *brain, void *ev)
{
    int id = *(int *)((char *)ev + 12);
    int flags = *(int *)((char *)ev + 16);
    int *v, n, idx;
    (void)brain;
    if (!master_live(dc_view))
        return 0;
    if (!(flags & 1) || (flags & 0x10) || (flags & 8))
        return 0;                               /* ignore key-repeat */
    if (id != 17 && id != 18)                   /* LEFT / RIGHT */
        return 0;
    v = *(int **)(dc_view + 124);
    n = (int)((*(int **)(dc_view + 128)) - v);
    if (!v || n <= 0)
        return 0;
    idx = *(int *)(dc_view + 144);
    if (idx < 0 || idx >= n)
        idx = 0;
    idx = (idx + (id == 18 ? 1 : n - 1)) % n;
    *(int *)(dc_view + 144) = idx;
    DN_INVALIDATE(dc_view);
    return 1;
}
