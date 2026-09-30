/* SPDX-License-Identifier: GPL-2.0-or-later
 * Core A master-insert helpers: the Digitone mk1 main CPU's audio render.
 * Digitone mk1 / Digitone Keys, OS 1.43. Addresses measured; see
 * elekloader-modding-guide/plans/digitone-dsp.md.
 *
 * The render ISR (0x4009d100) writes one 256-byte half of the SSI buffer per
 * block: 0x80001A00 + half*0x100, 32 frames of { int32 L, int32 R }. Which half
 * is chosen from the eDMA channel-54 source pointer (0xFC0456C0), read at the
 * start of the block. So a master effect is two event handlers:
 *   ev_render_in  -> dn_out_off()  (which half this block will write)
 *   ev_render_out -> process (DN_OUT_BASE + off, 256 bytes) in place
 * That is combinable: every mod is only a subscriber, no site, no conflict.
 */
#ifndef DIGITONE_COREA_H
#define DIGITONE_COREA_H

/* The Digitone mk1's vline/fillRect/frameRect, Signature: (bmp,x0,y0,x1,y1,c)
 * with y = 0 the BOTTOM row. (os153.inc/dn143.inc.) */
#define DN_VLINE     ((void (*)(void *, int, int, int, int))0x400DC92C)
#define DN_FILLRECT  ((void (*)(void *, int, int, int, int, int))0x400DD292)
#define DN_FRAMERECT ((void (*)(void *, int, int, int, int, int))0x400DD076)

#define DN_DMA_CH54_SADDR (*(volatile unsigned *)0xFC0456C0u)

#define DN_OUT_BASE  0x80001A00u
#define DN_OUT_HALF  0x100u
#define DN_OUT_FRAMES 32              /* stereo frames per block (256 bytes) */

/* The half the current block will write (the other one is being played). */
static inline unsigned dn_out_off(void)
{
    return (DN_DMA_CH54_SADDR < (DN_OUT_BASE + DN_OUT_HALF)) ? DN_OUT_HALF : 0u;
}

/* x*c/2^15 (c is Q15), the low 15 bits of x dropped: safe for any int32 x and
 * int16 c, no 64-bit product, no library call. Precision is ample for audio. */
static inline int dn_q15(int x, int c)
{
    return (x >> 15) * c;
}

/* x*d/2^14 for a small delta d (Q14): result is x*(1 + d/2^14), i.e. a gain
 * near 1 expressed as its deviation, which keeps the product in 32 bits. */
static inline int dn_q14d(int x, int d)
{
    return (x >> 14) * d;
}

#endif
