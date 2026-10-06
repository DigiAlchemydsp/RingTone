/* SPDX-License-Identifier: GPL-2.0-or-later
 * digifilter (Digitone mk1 / Digitone Keys, OS 1.43): extra filter modes on the
 * main CPU's voice stage.
 *
 * The Digitone's eight FM voices are rendered on the second CPU and land, one
 * 32-frame block at a time, in 0x80004110 (8 x 32 int32, Q1.31). The main CPU
 * then pans/levels them into the buses and runs the effects. We hook the render
 * just before the voice mix (site 0x4009e13e) and filter the selected voices in
 * place, so the stock engine, effects and outputs are untouched.
 *
 * Modes (Digi Filter's): BP and BP2 (a wider band pass) run a trapezoidal
 * state-variable filter (filter_dsp.s); COMB and TRASH run feedback combs
 * (TRASH at half the delay, a higher harmonic series). The same integer DSP as
 * the Digitakt mk1's Digi Filter, retuned for the Digitone's Q1.31 voice block.
 *
 * Performance: the cutoff and resonance are global, so the coefficients are
 * built ONCE per block (not once per voice), the smoothing is fractional (Q8)
 * and the tables are interpolated, and silent voices (an all-zero block with a
 * settled state) are skipped entirely. A voice that sounds costs one SVF run of
 * its 32 frames.
 *
 * Routing is per voice (the 8 voices are shared between the 4 tracks; the
 * main CPU's render only sees voices, not tracks). Encoder steps and the trig
 * keys toggle which voices are filtered.
 */
typedef int int32;
typedef unsigned int uint32;

#include "filter_tables.h"

#define DN_VOICE_BASE   0x80004110u     /* 8 voices x 32 int32, Q1.31 */
#define DN_VOICE_STRIDE 32             /* int32 per voice */
#define DN_VOICE_FRAMES 32
#define DN_NVOICES      8
/* Routing stays per voice, but at most this many are filtered at once: the
 * SVF/comb is the heaviest per-voice work on the main CPU, so a bounded load.
 * Lower it to 3 if a hot pattern still costs too much. */
#define DF_MAX_VOICES   4

/* exported parameters the DIGI FILTER page edits */
int digifilter_on = 0;                  /* the page's encoder A enables it */
int digifilter_mode = 0;                /* 0=BP 1=BP2 2=COMB 3=TRASH */
int digifilter_freq = 64;               /* 0..127 */
int digifilter_reso = 48;               /* 0..127 (the K27 table is 16 steps) */
int digifilter_vmask = (1 << DF_MAX_VOICES) - 1;  /* bit v -> filter voice v */

enum { DF_BP, DF_BP2, DF_COMB, DF_TRASH, DF_NMODES };
static const char *const DF_NAME[DF_NMODES] = { "BP", "BP2", "COMB", "TRASH" };

/* ---- 32-bit integer helpers (no FPU, no libgcc) ---- */

/* floor(a * b / 2^sh) for 16 <= sh <= 31, when the result fits 32 bits */
static inline __attribute__((always_inline)) int32 mulsh(int32 a, int32 b, int sh)
{
    uint32 ua = a < 0 ? -(uint32)a : (uint32)a, ub = b < 0 ? -(uint32)b : (uint32)b;
    uint32 al = ua & 0xffff, ah = ua >> 16, bl = ub & 0xffff, bh = ub >> 16;
    uint32 ll = al * bl, lh = al * bh, hl = ah * bl, hh = ah * bh;
    uint32 mid = (ll >> 16) + (lh & 0xffff) + (hl & 0xffff);
    uint32 lo = (ll & 0xffff) | (mid << 16);
    uint32 hi = hh + (lh >> 16) + (hl >> 16) + (mid >> 16);
    if ((a < 0) != (b < 0)) {
        lo = ~lo + 1;
        hi = ~hi + (lo == 0);
    }
    return (int32)((hi << (32 - sh)) | (lo >> sh));
}

/* floor(2^55 / d), d > 2^24 */
static int div55(uint32 d)
{
    uint32 rem = 1u << 23, q = 0;
    int i;
    for (i = 0; i < 32; i++) {
        uint32 carry = rem >> 31;
        rem <<= 1;
        q <<= 1;
        if (carry || rem >= d) {
            rem -= d;
            q |= 1;
        }
    }
    return (int32)q;
}

static int clampi(int v, int lo, int hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

/* linear interpolation of a table at a Q8 index: t[i] + (t[i+1]-t[i]) * frac.
 * The delta is split so no intermediate exceeds 32 bits (t holds Q27 values). */
static int interp_i(const int *t, int n, int q8)
{
    int i = q8 >> 8, f = q8 & 0xff, d;
    if (i < 0)
        return t[0];
    if (i >= n - 1)
        return t[n - 1];
    d = t[i + 1] - t[i];
    return t[i] + (d >> 8) * f + (((d & 0xff) * f) >> 8);
}

/* ---- the SVF (BP / BP2) ---- */

static int32 df_st[DN_NVOICES][2];

extern void digifilter_svf(int32 *buf, int frames, const int32 *coef, int32 *state);

/* coefficients from the interpolated g (Q27) and k (Q27) */
static void coef_from_gk(int32 g, int32 k, int32 *c)
{
    int32 d24;
    c[3] = -ONE27;                    /* c0 */
    c[4] = mulsh(k, ONE27, 27);       /* c1: out = c1 * band */
    c[5] = 0;                         /* c2 */
    d24 = (1 << 24) + mulsh(g, g + k, 30);
    c[0] = div55((uint32)d24);        /* a1 */
    c[1] = mulsh(g, c[0], 27);        /* a2 */
    c[2] = mulsh(g, c[1], 27);        /* a3 */
}

/* ---- the comb (COMB / TRASH) ---- */

#define DF_COMB_N 256
#define DF_COMB_MASK (DF_COMB_N - 1)
#define DF_COMB_LIMIT (1 << 30)
static int32 df_cbuf[DN_NVOICES][DF_COMB_N];
static int df_cpos[DN_NVOICES];
static int df_cinit[DN_NVOICES];
static int df_cdly[DN_NVOICES];      /* integer delay in samples */
static int32 df_cg[DN_NVOICES];      /* Q27 feedback */
static int32 df_ceng[DN_NVOICES];    /* OR of the last block written: tail energy */

/* Simpler comb: an integer delay (no fractional read, no per-sample smoothing)
 * and one feedback multiply per sample. The delay and feedback glide once per
 * block instead, which is cheap and still click-free. */
static void comb_run(int32 *buf, int frames, int fi, int qi, int v, int div)
{
    int32 target = COMB_DELAY[fi] / div;
    int32 gt = (int32)(qi >> 3) * (ONE27 / 16);   /* reso 0..127 -> 0..0.9375 */
    int32 *b = df_cbuf[v];
    int32 orv = 0;
    int d, p, i, j;
    if (target < 3)
        target = 3;
    if (target > DF_COMB_MASK)
        target = DF_COMB_MASK;
    if (!df_cinit[v]) {
        df_cinit[v] = 1;
        df_cdly[v] = target;
        df_cg[v] = gt;
        df_cpos[v] = 0;
        for (j = 0; j < DF_COMB_N; j++)
            b[j] = 0;
    }
    df_cdly[v] += (target - df_cdly[v]) >> 2;    /* settle over a few blocks */
    df_cg[v] += (gt - df_cg[v]) >> 3;
    d = df_cdly[v];
    if (d < 3) d = 3;
    if (d > DF_COMB_MASK) d = DF_COMB_MASK;
    p = df_cpos[v];
    for (i = 0; i < frames; i++) {
        int32 x = buf[i], val, y, ga, va;
        val = b[(p - d) & DF_COMB_MASK];
        ga = df_cg[v] >> 12;
        va = val >> 11;                          /* (g*val)>>27 == ((g>>12)*(val>>11))>>4 */
        y = x + ((ga * va) >> 4);
        if (y > DF_COMB_LIMIT)
            y = DF_COMB_LIMIT;
        else if (y < -DF_COMB_LIMIT)
            y = -DF_COMB_LIMIT;
        b[p] = y;
        p = (p + 1) & DF_COMB_MASK;
        buf[i] = y;
        orv |= y;
    }
    df_cpos[v] = p;
    df_ceng[v] = orv;
}

/* ---- the hooked entry (filter_glue.s) ---- */

static int df_prev[DN_NVOICES] = { -1, -1, -1, -1, -1, -1, -1, -1 };
static int df_was_on;

/* smoothed cutoff/resonance, Q8, one fractional step per block (glide) */
static int df_fi_q8 = 64 << 8;
static int df_qi_q8 = 48 << 8;

void digifilter_run(void)
{
    int32 *base = (int32 *)DN_VOICE_BASE;
    int m, fi, qi, v, i, used = 0;
    int32 g, k, c[6];

    if (!digifilter_on || !(digifilter_vmask & 0xff)) {
        df_was_on = 0;
        return;
    }
    m = clampi(digifilter_mode, 0, DF_NMODES - 1);

    /* Smoothed, fractional cutoff/resonance: a first-order glide (~8 blocks,
     * about 5 ms) so a knob move or a mode change never steps. */
    df_fi_q8 += ((clampi(digifilter_freq, 0, 127) << 8) - df_fi_q8) >> 3;
    df_qi_q8 += ((clampi(digifilter_reso, 0, 127) << 8) - df_qi_q8) >> 3;
    fi = df_fi_q8 >> 8;
    qi = df_qi_q8 >> 8;                 /* reso 0..127 */

    /* One coefficient set for the block, shared by every voice. */
    g = interp_i(G27, 128, df_fi_q8);
    k = (m == DF_BP2) ? interp_i(K27, 16, df_qi_q8 >> 4)     /* ~half the Q */
                      : interp_i(K27, 16, df_qi_q8 >> 3);    /* K27 index = reso/8 */
    coef_from_gk(g, k, c);

    if (!df_was_on) {                    /* coming back from bypass: fresh */
        df_was_on = 1;
        for (v = 0; v < DN_NVOICES; v++) {
            df_st[v][0] = df_st[v][1] = 0;
            df_cinit[v] = 0;
            df_ceng[v] = 0;
            df_prev[v] = -1;
        }
    }

    for (v = 0; v < DN_NVOICES && used < DF_MAX_VOICES; v++) {
        int32 *buf;
        int acc = 0;
        if (!((digifilter_vmask >> v) & 1))
            continue;
        buf = base + v * DN_VOICE_STRIDE;
        /* A voice that is silent and settled costs nothing: skip it. For the
         * SVF "settled" is the state pair; for the comb it is the tail energy
         * the last block wrote into the delay line. */
        if (m <= DF_BP2) {
            for (i = 0; i < DN_VOICE_FRAMES; i++)
                acc |= buf[i];
            if (!acc && !df_st[v][0] && !df_st[v][1])
                continue;
        } else {
            for (i = 0; i < DN_VOICE_FRAMES; i++)
                acc |= buf[i];
            if (!acc && !df_ceng[v])
                continue;
        }
        used++;                          /* counts toward the routing cap */
        if (df_prev[v] != m) {           /* mode change: restart this voice */
            df_st[v][0] = df_st[v][1] = 0;
            df_cinit[v] = 0;
            df_ceng[v] = 0;
            df_prev[v] = m;
        }
        if (m <= DF_BP2)
            digifilter_svf(buf, DN_VOICE_FRAMES, c, df_st[v]);
        else
            comb_run(buf, DN_VOICE_FRAMES, fi, qi, v, m == DF_COMB ? 1 : 2);
    }
}

/* ---- the DIGI FILTER page (drawn by digictl) ---- */

#define DN_TEXTF  ((void (*)(void *, const void *, int, int, int, const char *, ...))0x400DDE68)
#define DN_FONT5  ((const void *)0x402315C8)
#define DN_FILLRECT ((void (*)(void *, int, int, int, int, int))0x400DD292)
#define DN_FRAMERECT ((void (*)(void *, int, int, int, int, int))0x400DD076)

/* the voice menu's voice indicator: a 5x5 outlined box, filled when the voice
 * is active (the LAYER element, drawn with frameRect + fillRect). Reused here
 * for the V1..V8 routing toggles. */
static void df_voice_box(void *bmp, int x, int y, int on)
{
    DN_FRAMERECT(bmp, x, y, x + 5, y + 5, 1);
    if (on)
        DN_FILLRECT(bmp, x + 1, y + 1, x + 4, y + 4, 1);
}

void digifilter_page_draw(void *bmp)
{
    int m = clampi(digifilter_mode, 0, DF_NMODES - 1);
    int i;
    DN_FILLRECT(bmp, 0, 0, 127, 51, 0);
    DN_TEXTF(bmp, DN_FONT5, 1, 46, -1, "DIGI FILTER");
    DN_TEXTF(bmp, DN_FONT5, 96, 46, -1, digifilter_on ? "ON" : "OFF");
    DN_TEXTF(bmp, DN_FONT5, 1, 38, -1, "MODE %s", DF_NAME[m]);
    DN_TEXTF(bmp, DN_FONT5, 1, 30, -1, "%d", digifilter_freq);
    DN_TEXTF(bmp, DN_FONT5, 18, 30, -1, "FREQ");
    DN_TEXTF(bmp, DN_FONT5, 70, 30, -1, "%d", digifilter_reso);
    DN_TEXTF(bmp, DN_FONT5, 82, 30, -1, "RESO");
    DN_TEXTF(bmp, DN_FONT5, 1, 22, -1, "VOICES (max %d)", DF_MAX_VOICES);
    for (i = 0; i < 8; i++) {
        int x = 50 + i * 9;
        df_voice_box(bmp, x, 13, (digifilter_vmask >> i) & 1);
        DN_TEXTF(bmp, DN_FONT5, x, 6, -1, "%d", i + 1);
    }
    DN_TEXTF(bmp, DN_FONT5, 1, 0, -1, "TRIG 1-8 = VOICES");
}

int digifilter_page_enc(int id, int d)
{
    if (!d)
        return 1;
    switch (id) {
    case 1: digifilter_on = (d > 0); break;
    case 2: digifilter_mode = clampi(digifilter_mode + (d > 0 ? 1 : -1), 0, DF_NMODES - 1); break;
    case 3: digifilter_freq = clampi(digifilter_freq + d, 0, 127); break;
    case 4: digifilter_reso = clampi(digifilter_reso + d, 0, 127); break;
    case 5: digifilter_vmask = (1 << DF_MAX_VOICES) - 1; break;
    case 6: digifilter_vmask = 0x00; break;
    default: return 0;
    }
    return 1;
}

/* ev_key ids: trig 1..8 are 26..33. At most DF_MAX_VOICES may be routed. */
int digifilter_page_key(int id, int flags)
{
    (void)flags;
    if (id >= 26 && id <= 33) {
        int bit = 1 << (id - 26);
        if (digifilter_vmask & bit) {
            digifilter_vmask &= ~bit;
        } else {
            int n = 0, i;
            for (i = 0; i < DN_NVOICES; i++)
                n += (digifilter_vmask >> i) & 1;
            if (n < DF_MAX_VOICES)
                digifilter_vmask |= bit;
        }
        return 1;
    }
    return 0;
}
