# Reverb algorithms for the Digitone mk1 (ColdFire) — ranked list

Hardware constraints that decide the choice:

- **ColdFire MCF5441x, 250 MHz, NO FPU** — integer only, no libc, no 64-bit mul.
- **The bus, not the ALU, is the cost.** Every delay-line read/write is a DDR
  access; a reverb with N delay structures does ~2·N memory ops per sample.
  The emulator models the ALU well but **under-counts DDR**, so a build that
  looks fine in digiemu can still overrun on hardware.
- **Hard render deadline.** 32-frame blocks, 1500/s, 166,667 cycles/block;
  overrunning it *hangs the unit* (that is what the full-rate Dattorro did).
- Already measured here: FDN-4 half-rate ≈ **+20k**, Dattorro full-rate ≈
  **+37k** (both cycles/block, worst case).

`cyc/block` below are estimates from the structure count (measured where noted),
for a **mono** reverb at **full 48 kHz rate**. **Half-rate halves them.**

| # | algorithm | delay structs | ~cyc/block | RAM (mono s16) | sound | fit |
|---|---|---|---|---|---|---|
| 1 | **Multi-tap feedback delay** ("splash") | 1 line, 3–4 taps + 1 write | **3–8 k** | 8–32 KB | smeared delay, not a true reverb | cheapest; the recreation's GRAIN |
| 2 | **Schroeder** | 4 comb + 2 allpass = 6 | **10–14 k** | ~8 KB | metallic, classic room | great CPU/quality |
| 3 | **Freeverb, 4 combs** | 4 comb + 2 allpass = 6 | **10–14 k** | ~6 KB | small room | great CPU/quality |
| 4 | **Freeverb, 8 combs (mono)** | 8 comb + 4 allpass = 12 | **18–24 k** | ~27 KB | hall/room — good | **best simple reverb** |
| 5 | **FDN 4-line** (+4 diffusion) | 4 lines + 4 allpass | ~20 k (measured, half-rate) | ~16 KB | dense, good | what 0.4w used |
| 6 | **Dattorro plate** | 4 in-ap + tank(4 ap/delay) = 14 | ~37 k (measured, full) | ~90 KB | plate | too heavy full-rate |
| 7 | Moorer / Gardner | 20+ | >50 k | large | high quality | no |
| 8 | Velvet-noise / sparse FIR diffusion | 1 sparse tap set | 6–12 k | small | modern diffuse, no tank | cheap diffusion option |

## Recommendation

**Freeverb, mono, 8 combs + 4 allpasses, at half rate** — a genuine, well-behaved
reverb at roughly **half the Dattorro cost** (~10–12 k), all integer, and it is
the classic "simple plate/room" everyone knows. If you want the absolute floor,
**Schroeder / Freeverb-4** (~10–14 k full rate) or the **multi-tap splash**
(~3–8 k) for a smear rather than a room.

Why Freeverb fits ColdFire better than a Dattorro/FDN:
- A **comb** is one read + one write + a feedback mul + a one-pole damping mul.
  There is **no mixing matrix** and no cross-coupling maths.
- **Allpasses are shared-style and short** (225–556 samples), so the hot buffers
  are small and stay in cache better.
- The whole thing is a straight-line loop of independent structures — no data
  dependency chains, so the ColdFire pipelines it well.

## ColdFire micro-optimizations (apply to whichever we pick)

1. **Half-rate (or quarter-rate) the reverb** — the single biggest win; the tail
   just loses bandwidth. Hold the wet across the skipped frames.
2. **Mono** — one line per structure, not two (already done for the family).
3. **s16 lines, power-of-two where a mask avoids a compare wrap.**
4. **No divides in the loop** — precompute coefficients per block, use shifts.
5. **Exact bypass when off** (no warm-line writes) — the family already does this.
6. **16-byte alignment** on the lines; keep the hot buffers small.
7. **Damping** as a one-pole (`s += (x-s)*c>>15`, one mul), not a biquad.
8. Optional: **EMAC** for the per-sample muls (exact 32×32→64 in one op) — no
   sound change; needs `MACSR` discipline.

## Why the Dattorro froze (for the record)

The full-rate Dattorro is ~14 delay structures at 48 kHz → ~37k cycles/block on
top of a render already near 60 % busy; with the FM voices it crossed the
deadline and the unit hung. Half-rating it would bring it to ~18k, but it is
still the heaviest credible option and its 90 KB of lines are cache-unfriendly.
The measured data above is why **Freeverb/Schroeder is the right pick here**.
