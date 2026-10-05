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
 * The combs are the Digitakt's smoothed, fractional-delay combs: the delay and
 * feedback glide per sample and the delay tap is linearly interpolated, so
 * sweeping FREQ / RESO / the four COMB knobs does not step or click. All four
 * comb controls fit on the one DIGI FILTER page (there is no per-track envelope
 * to expose here, unlike the Digitakt): DLY delay offset, HARM harmonics
 * divider, DAMP damping, FB feedback trim.
 *
 * Performance: the cutoff and resonance are global, so the coefficients are
 * built ONCE per block (not once per voice), cached while the smoothed indices
 * hold steady, the smoothing is fractional (Q8) and the tables are
 * interpolated, and silent voices (an all-zero block with a settled state) are
 * skipped before any work is done (including the coefficient build). A voice
 * that sounds costs one SVF run of its 32 frames.
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
/* the four COMB/TRASH knobs (0..127, one step per notch, like the rest). Their
 * defaults leave the comb exactly as it was. */
int digifilter_delay = 0;               /* DLY: delay offset, samples */
int digifilter_harm = 0;                /* HARM: delay divider 1..4 (0 = 1) */
int digifilter_damp = 0;                /* DAMP: one-pole damping on the tail */
int digifilter_fb = 0;                  /* FB: feedback trim toward self-osc */

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
static int32 df_cdly[DN_NVOICES];    /* Q16 smoothed delay in samples */
static int32 df_cg[DN_NVOICES];      /* Q27 smoothed feedback */
static int32 df_clp[DN_NVOICES];     /* Q27 one-pole state for the damping */
static int32 df_ceng[DN_NVOICES];    /* OR of the last block written: tail energy */

/* Feedback comb, fractional and smoothed (the Digitakt Digi Filter's comb):
 * y = x + g*y[n-D]. D = COMB_DELAY[fi] / (div*hdiv) + dly_off, clamped 3..255.
 * The delay and feedback glide per sample and the delay tap is linearly
 * interpolated, so a moving cutoff / envelope / knob does not step or click;
 * the output is saturated so high feedback cannot run away. The interpolation
 * and the feedback each use a single 32x32 multiply:
 *   (fp*diff)>>16 == ((fp>>1)*((diff)>>13))>>2
 *   (g*val)>>27   == ((g>>12)*(val>>11))>>4
 * COMB uses div 1; TRASH uses div 2 for a higher harmonic series. The four knobs
 * are delay offset (samples), harmonics divider (1..4), damping (one-pole on the
 * tail) and feedback trim (push toward self-oscillation). */
static void comb_run(int32 *buf, int frames, int fi, int qi, int v, int div,
                     int dly_off, int hdiv, int damp, int fbtrim)
{
    int32 target = COMB_DELAY[fi] / (div * hdiv) + dly_off;
    int32 tdq, gt, dampq, *b = df_cbuf[v];
    int32 orv = 0;
    int p, i, j;
    if (target < 3)
        target = 3;                  /* taper: no near-Nyquist comb */
    if (target > DF_COMB_MASK)
        target = DF_COMB_MASK;
    tdq = target << 16;
    gt = (int32)(qi >> 3) * (ONE27 / 16);            /* reso 0..127 -> 0..0.9375 */
    if (fbtrim) {
        gt += mulsh(ONE27 - gt, fbtrim * 258, 15);   /* up toward full feedback */
        if (gt > 0x7c000000)
            gt = 0x7c000000;                         /* stay short of runaway */
    }
    dampq = damp * 258;                              /* 0..127 -> Q15 */
    if (!df_cinit[v]) {
        df_cinit[v] = 1;
        df_cdly[v] = tdq;            /* start at the target, no glide-in */
        df_cg[v] = gt;
        df_clp[v] = 0;
        df_cpos[v] = 0;
        for (j = 0; j < DF_COMB_N; j++)
            b[j] = 0;
    }
    p = df_cpos[v];
    for (i = 0; i < frames; i++) {
        int32 ds, ip, fp, i0, i1, x, val, y, fa, da, ga, va;
        df_cdly[v] += (tdq - df_cdly[v]) >> 6;       /* ~64 samples (1.3 ms) */
        df_cg[v] += (gt - df_cg[v]) >> 7;
        ds = df_cdly[v];
        ip = ds >> 16;
        fp = ds & 0xffff;
        i0 = (p - ip) & DF_COMB_MASK;
        x = buf[i];
        if (fp) {                    /* interpolate only while the delay glides */
            i1 = (i0 - 1) & DF_COMB_MASK;
            fa = fp >> 1;
            da = (b[i1] - b[i0]) >> 13;
            val = b[i0] + ((fa * da) >> 2);
        } else {
            val = b[i0];             /* settled: an integer tap, no multiply */
        }
        if (damp) {                  /* DAMP: darken the tail */
            df_clp[v] += (val - df_clp[v]) >> 4;
            val += mulsh(df_clp[v] - val, dampq, 15);
        }
        ga = df_cg[v] >> 12;
        va = val >> 11;
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

/* The block's SVF coefficients, rebuilt only when the smoothed indices (or the
 * mode) change, so a settled filter costs no interp / div55 at all. */
static int32 df_coef[6];
static int df_cc_m = -1, df_cc_fi8 = -1, df_cc_qi8 = -1;

void digifilter_run(void)
{
    int32 *base = (int32 *)DN_VOICE_BASE;
    int m, fi, qi, v, i, nproc = 0;
    int proc[DF_MAX_VOICES];

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

    if (!df_was_on) {                    /* coming back from bypass: fresh */
        df_was_on = 1;
        df_cc_m = -1;
        for (v = 0; v < DN_NVOICES; v++) {
            df_st[v][0] = df_st[v][1] = 0;
            df_cinit[v] = 0;
            df_ceng[v] = 0;
            df_prev[v] = -1;
        }
    }

    /* Pick the voices to process: routed, not silent-and-settled, capped. A
     * voice that is silent and settled costs nothing. For the SVF "settled" is
     * the state pair; for the comb it is the tail energy the last block wrote
     * into the delay line. */
    for (v = 0; v < DN_NVOICES && nproc < DF_MAX_VOICES; v++) {
        int32 *buf;
        int acc = 0, settled;
        if (!((digifilter_vmask >> v) & 1))
            continue;
        buf = base + v * DN_VOICE_STRIDE;
        for (i = 0; i < DN_VOICE_FRAMES; i++)
            acc |= buf[i];
        settled = (m <= DF_BP2) ? (!df_st[v][0] && !df_st[v][1])
                                : (!df_ceng[v]);
        if (!acc && settled)
            continue;
        proc[nproc++] = v;
    }
    if (!nproc)
        return;                          /* nothing sounding: no work at all */

    if (m <= DF_BP2) {
        if (m != df_cc_m || df_fi_q8 != df_cc_fi8 || df_qi_q8 != df_cc_qi8) {
            int32 g = interp_i(G27, 128, df_fi_q8);
            int32 k = (m == DF_BP2) ? interp_i(K27, 16, df_qi_q8 >> 4)  /* ~half the Q */
                                    : interp_i(K27, 16, df_qi_q8 >> 3); /* index = reso/8 */
            coef_from_gk(g, k, df_coef);
            df_cc_m = m; df_cc_fi8 = df_fi_q8; df_cc_qi8 = df_qi_q8;
        }
        for (i = 0; i < nproc; i++) {
            v = proc[i];
            if (df_prev[v] != m) {       /* mode change: restart this voice */
                df_st[v][0] = df_st[v][1] = 0;
                df_prev[v] = m;
            }
            digifilter_svf(base + v * DN_VOICE_STRIDE, DN_VOICE_FRAMES,
                           df_coef, df_st[v]);
        }
    } else {
        int div = (m == DF_COMB) ? 1 : 2;
        int hdiv = 1 + (digifilter_harm * 3) / 127;      /* 1..4, 0 = none */
        for (i = 0; i < nproc; i++) {
            v = proc[i];
            if (df_prev[v] != m) {       /* mode change: restart this voice */
                df_cinit[v] = 0;
                df_ceng[v] = 0;
                df_prev[v] = m;
            }
            comb_run(base + v * DN_VOICE_STRIDE, DN_VOICE_FRAMES, fi, qi, v,
                     div, digifilter_delay, hdiv, digifilter_damp,
                     digifilter_fb);
        }
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
    /* the four COMB/TRASH knobs, all on one row (no room for a second page) */
    DN_TEXTF(bmp, DN_FONT5, 1, 22, -1, "%d DLY %d HARM %d DMP %d FB",
             digifilter_delay, digifilter_harm, digifilter_damp, digifilter_fb);
    for (i = 0; i < 8; i++) {
        int x = 50 + i * 9;
        df_voice_box(bmp, x, 13, (digifilter_vmask >> i) & 1);
        DN_TEXTF(bmp, DN_FONT5, x, 6, -1, "%d", i + 1);
    }
    DN_TEXTF(bmp, DN_FONT5, 1, 0, -1, "TRIG 1-8 = VOICES (max %d)", DF_MAX_VOICES);
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
    case 5: digifilter_delay = clampi(digifilter_delay + d, 0, 127); break;   /* DLY */
    case 6: digifilter_harm = clampi(digifilter_harm + d, 0, 127); break;     /* HARM */
    case 7: digifilter_damp = clampi(digifilter_damp + d, 0, 127); break;     /* DMP */
    case 8: digifilter_fb = clampi(digifilter_fb + d, 0, 127); break;         /* FB */
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
