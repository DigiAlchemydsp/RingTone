# Tone+FX — DSP, CPU and footprint notes (Digitone mk1, OS 1.43)

What the suite's code does, how it is built, the fixed-point conventions, the
optimization methods used (and why), what is repurposed from the stock OS and
from RingTone, and the RAM / flash / headroom ledger. This is the technical
companion to `HANDOFF.md`; `DSP.md` is the address/architecture reference.

Current package: `tonefx 3.5p` (`.run 27475`, `.bss 19446`, `imports nothing`).
The `perf-opt` ledger is §9 and the fixes that landed with it are §10.

## 1. Where the code runs

Two ColdFire MCF5441x CPUs (`DSP.md`):

- **Core A (main CPU)** — UI, sequencer, **effects and the mix**. Every master
  FX in this suite is here.
- **Core B ("DSP")** — the eight FM voices. Not touched by the suite.

The suite is **subscription-only**: it never patches a stock instruction. Each
FX is a handler on the core's render events:

- `ev_render_in` (`void f(void)`, order 40/50) — remembers which half of the
  output buffer this block writes: `dn_out_off()` reads eDMA ch54's SADDR
  `0xFC0456C0` and returns `0x100` or `0`.
- `ev_render_out` (order 50..65) — processes `0x80001A00 + off` (256 B,
  **32 stereo frames, int32, 24-bit left-justified**) in place.

Interrupt level, 1500 blocks/s, 48 kHz, 667 us per block. Handlers are
`void f(void)`; d1/a0/a1 are free; the EMAC is saved/restored by the core, but a
handler that uses it must leave `MACSR` as found.

**Chain order** is the `ev_render_out` order:
`ring(50) → EQ(55) → crush(57) → fold(60) → wave(62) → meter(65)`.

## 2. Module inventory

| mod | source | lines | stage / role |
|---|---|---|---|
| `digimeter` | `meter.c` | 62 | L/R peak (log bars), scanned from the output half; read by the page |
| `digieq` | `eq.c` | 63 | one-pole low/high split; low/high shelf, Q14 gains |
| `digiring` | `ring.c` | 59 | 256-entry Q15 sine carrier; ring/tremolo |
| `digicrush` | `crush.c` | 106 | BITS mask / SR hold / CRUNCH clip — one stateless stage |
| `digifold` | `fold.c` | 100 | triangle wavefolder + hard-clip overdrive |
| `digiwave` | `wave.c` | 275 | WOB/SHFT/FLAN/PAN/WIDE, one 16 KB delay line + one LFO |
| `digictl` | `digictl.c` + `cc_glue.s` | ~730 + 28 | the 6 master pages (RING/FOLD/TILT/CRUSH/PITCH/STEREO) + the PERFORM page, encoders, keys, per-pattern store, MIDI CC, momentary trig pads |
| `tonesplash` | `render.c` + `splash.s` | 212 + 18 | boot wordmark (intro only) |
| shared | `src/corea.h`, `src/sin256.h` | 56 + 39 | Core A helpers + sine table |

Total ≈ 1,633 lines (C+asm+headers); 1,833 with `mod.json`s.

## 2b. Per-block CPU footprint (Core A)

All of it is **Core A**; the suite's **DSP (Core B) footprint is 0**. Costs are
per **active** stereo frame (32 frames/block, 1500 blocks/s), approximate, from
the compiled inner loops (`m68k-elf-objdump`) plus the source. A **bypassed**
section costs ~0 (see §4.3).

| # | block / mode | ≈ insn/frame | driver |
|---|---|---|---|
| 1 | `digicrush` — BITS | ~10 | AND mask (dither adds ~12: LFSR muls) |
| 2 | `digicrush` — SR | ~12 | hold counter, 2 loads / 2 stores |
| 3 | `digimeter` | ~15 | 2 loads + abs + compare (no mul) |
| 4 | `digiwave` — WIDE | ~18 | 2× `dn_mul14` + mid/side |
| 5 | `digifold` — CLEAN / MUD | ~20 | 2× Q8 gain + reflect |
| 6 | `digiwave` — PAN | ~24 | 3× `dn_mul15` + pan law |
| 7 | `digicrush` — CRUNCH | ~25 | 2× Q8 gain + clamp |
| 8 | `digiring` | ~28 | `sin256` interp + 2× `dn_mul15` |
| 9 | `digieq` | ~30 | one-pole + 2× `dn_mul14` |
| 10 | `digifold` — DIST / TRSH | ~35 | + 2× drive (gain → clamp) |
| 11 | `digiwave` — WOB | ~45 | 2 interpolated delay reads + blend |
| 12 | `digiwave` — FLAN | ~55 | WOB + feedback write |
| 13 | `digiwave` — SHFT | ~75 | 8 loads, 4 interp muls, window + crossfade |

Compiled `_render_out` sizes corroborate (whole function incl. setup / all
modes): `meter 162 · eq 322 · ring 326 · fold 356 · crush 476 · wave 2178`.

Notes: the delay modes (WOB/FLAN/SHFT) are ALU-light but touch the 16 KB **delay
line in DDR**, whose accesses cost more than the instruction count implies. The
whole suite runs on Core A; reduce DSP load only via fewer/blanked FM voices
(`ev_voice_on` / section 7).

## 3. Fixed-point rules (why the code looks the way it does)

- **No FPU** on the MCF5441x, **no libc, no `memcpy`/`memset`, no 64-bit
  multiply helper**. All arithmetic is integer, and `build.py` reports
  `imports nothing` — that is a hard constraint, not a nicety.
- The master bus is **int32, 24-bit left-justified**; the factory pattern peaks
  near `2^21`, so headroom for gain is ~13 bits before clipping at 24 bits.
- Helpers (`src/corea.h`):
  - `dn_q15(x,c)   = (x>>15)*c` — cheap, quantizes in steps of `c`.
  - `dn_q14d(x,d)  = (x>>14)*d` — cheap gain near 1.
  - **`dn_mul15(x,c) = (x>>15)*c + (((x & 0x7fff)*c)>>15)`** — exact
    `(x*c)>>15` with 32-bit ops only. The cheap form quantized the ring/EQ wet
    signal in steps of the carrier (~-36 dB noise); the two-term form removed
    that, at the cost of one extra multiply.
  - `dn_mul14` is the same for a Q14 coefficient.
- **No `-ffast-math`, no floats anywhere.**

## 4. Optimization methods used

Ordered roughly by how much they bought.

1. **Master-insert subscription, not a patch.** Because every FX is just an
   `ev_render_in`/`out` handler, all modules combine, there is no byte conflict,
   and the chain order is data (`order`), not code. Zero stock-byte footprint
   for the FX themselves.
2. **Block-rate parameter + per-sample ramp.** Targets are read from globals
   once per block and stepped across the 32 frames
   (`step = (target - cur) >> 5`), so knob moves and bypass are click-free with
   no per-sample condition tests. Used by ring, EQ, fold, wave.
3. **Click-free ramped true bypass (per section).** Each section's amount ramps
   to its **neutral value** over ~1 block (ring depth 0, EQ flat, fold amount 0,
   crush amount 0, WAVE per-mode neutral: WOB wet 0, FLAN mix 0, SHFT dry,
   PAN centre, WIDE 64), and once settled the handler `return`s **before any
   per-sample loop** — a true bypass with zero per-sample cost and an exact
   passthrough. This replaced the hard on/off for fold/crush/WAVE (which
   clicked) and fixed crush's bit mapping so amount 0 is identity (24 bits, not
   16). WAVE's SHFT mode gained a dry/wet fade so it can bypass cleanly; PAN and
   WIDE now ramp too.
4. **Block-rate LFO (one sine per block).** `digiwave` and `digiring` evaluate
   `sin256` at the block start and a linear per-sample step
   (`lstep = (sin(next) - sin(now)) >> 5`), replacing a per-sample sine
   (≈8 instructions/frame) with one multiply-free add.
5. **Fractional, clamped, interpolated swept delay** (`digiwave` WOB/FLAN).
   The first cut used an integer delay and a modulation span larger than the
   base delay, so the read index both stepped by whole samples and could go
   **negative** (`(wv_w + WV_N - (unsigned)d)` wrapped to garbage) — audible
   clicks. The fix: delay in **Q16.16**, read through `wv_read` (linear
   interpolation), and **clamp to >= 2 samples** so it can never wrap.
6. **Guard sample.** `wv_buf[ch][WV_N]` mirrors index 0, so a fractional read
   at `idx+1` needs no `& WV_MASK`.
7. **Derived + collapsed crossfade window (SHFT).** The two grains' windows are
   complementary, so the mix is
   `g0*w0 + g1*(1-w0) = g1 + (g0-g1)*w0` — **one multiply per channel instead of
   two**, and no second table lookup.
8. **Shared read position (SHFT).** `idx`/`frac` are computed once per grain and
   used for both L and R, instead of twice per channel.
9. **Precomputed tables.** `sin256` (Q15) is shared by ring, the wave LFO and
   the UI; `wv_ratio[128]` (Q16.16 `2^(semi/12)`) and `wv_win[256]` (Q15
   triangle) are `const` in `.run`, built at compile time.
10. **Stateless stage selection** (`crush`): BITS/SR/CRUNCH are chosen once per
    block; only one runs, so a bypassed branch costs nothing.
11. **Cheapest viable saturator.** fold's overdrive and crush's CRUNCH are a
    single Q8 multiply + two compares (stateless), not a `tanh`.
12. **Shared infrastructure / one engine, two WAVE pages.** One per-pattern
    store, one CC router `jmp`, one page factory and one invalidate path serve
    all modules. `digiwave`'s five modes are split over **two pages** — kind 4
    PITCH (WOB / SHFT) and kind 5 STEREO (FLAN / PAN / WIDE) — over one shared
    delay engine. Each page has its **own mode** (`digiwave_pmode`,
    `digiwave_smode`) so a page only ever shows and selects its own modes, plus
    an active-group flag (`digiwave_page`) set when a page is edited, which
    decides which mode the engine runs. Speed/depth are shared; mix/feedback are
    STEREO (FLAN). Feedback is capped at **0.75** (`fb = fb_knob*24575/127`) to
    keep the flanger from self-oscillating into distortion.
13. **Per-mod compiler flags (A/B, measured).** `mod.json` accepts `cflags`,
    appended after the device `-O2` (`elekloader/sdk/build.py:125`):

    | flags | `.run` | `.bss` | note |
    |---|---|---|---|
    | `-O2` (default) | 20528 | 25262 | imports nothing |
    | `-O3 -funroll-loops` | 35112 | 25230 | **imports `memset`** (loop distribution) — unusable |
    | `-O3 -fno-tree-loop-distribute-patterns` | 24152 | 25230 | +28 % code, imports nothing |

    Kept at `-O2`: `-O3` nearly doubles the code (or +28 % without loop
    distribution) for an unmeasured cycle gain, and unrolling reintroduces a
    `memset` dependency the no-libc build cannot satisfy. **Measured on the
    `3.5d` suite (perf-opt): `-O3 -fno-tree-loop-distribute-patterns` is a
    regression** — `.run` 27199 → 32997, `cftiming` render worst 99572 →
    99971 cyc, mean 99143.5 → 99536.7, margin 0.4026 → 0.4002, and *more*
    instructions. `-O2` stays.
14. **Output ceiling (`digictl_limit_out`, order 64).** A cheap soft limiter on
    the final mix: below a knee (~-2.5 dBFS) it is transparent; above it the
    excess is halved and hard-capped at ~-0.7 dBFS, so a hot flanger-feedback /
    pitch-shift / drive setting never reaches 24-bit clipping (0x7fffff).
    `digicrush`'s drive and `digifold` already clamp their own output; the
    flanger feedback write is clamped at the top of the delay loop too.
15. **Six passes over the buffer (identified, not yet fused).** Today ring, EQ,
    crush, fold, wave and meter each loop the 32 frames, so each frame is
    loaded/stored ~6 times. A single fused `tonefx_master()` loop (load L/R
    once, run the stages inline, store once) is the next big win — see §8.
16. **PERFORM page: static draw + cheap momentary pads.** The page (kind 6,
    reached with UP) has no animated graphics — the same pixels every frame.
    Its 16 trigs are momentary pads, one block per engine that ramp the engine's
    depth in `ev_render_in` (`pf_apply`), one step per block, and restore the
    pattern value on release. It costs a single flag test when idle, writes no
    store, and the ramp is a handful of integer ops only while a pad (or its
    release) is live. Each engine has its own depth: fold/crush are separate and
    the WAVE engine has independent PITCH / STEREO depths.

## 5. Repurposed / reused

- **`sin256.h`** — carried over from RingTone; now shared by ring, the wave LFO
  and the RING page animation.
- **The RingTone code base** — `meter.c`, `eq.c`, `ring.c`, `fold.c`,
  `digictl.c` are the original suite modules, extended here.
- **The master view's page vector.** The stock master view keeps its page kinds
  in a vector at `view+124`; `digictl` **appends** kinds 0–6 (RING, FOLD, TILT,
  CRUSH, PITCH, STEREO, PERFORM) after the stock pages and patches only the
  view's draw slot (`0x40199BBC`). No stock page is taken.
- **The unused MIDI-track 64-byte block.** Each pattern's four MIDI tracks
  leave `track+0x100` zero in all 128 slots and the OS never writes it;
  `digictl` uses `pattern+0x1040` for the **"DGX1"** per-pattern store
  (`v10`, 28 int16, 64 of 64 bytes — full).
- **The parked LFO bridge** (`digimod_dest`/`digimod_voice`, per-voice FLTR
  FREQ read at `0x80003544`) is kept in the store but has no page yet.
- **The stock CC router** (`0x400ED94E`) is hooked once (`cc_glue.s`, `op:"jmp"`)
  and dispatches to `digictl_cc_apply`; only CCs the stock table does not use
  are taken.
- **The intro draw/flush sites** (9 call sites) are reused by `tonesplash`.
- **The EMAC** is left to the core's save/restore; the FX avoid it today (see
  §8) but the render already pays its save/restore.
- **`build.py` size reporting / the linker** reports `imports nothing`, which is
  what keeps the no-libc build honest.

## 6. Footprint / headroom ledger (3.2b)

| item | value |
|---|---|
| `.run` (code + rodata) | 22,722 B |
| `.bss` (RAM state) | 25,390 B |
| — of which `digiwave` delay line | 2048 × 2 × 4 = 16,384 B (+8 guard) |
| — of which tables (`sin256`, `wv_ratio`, `wv_win`) | ~1,024 + 512 + 512 B (`.run`) |
| **RAM spare** | **~86 KB of 128 KB** |
| flash spare (3.2b patch) | ≈1.69 MB |
| sites / relocations | 11 / 646; imports nothing |

Budgets: `.run`+`.bss` share 128 KB across every linked mod; the delay line is
the single largest allocation. If it ever needs to grow, the `bulk` region
(0x44000000–0x47BE0000) needs core-dn1 3.2 as a claimed region; today the suite
runs on core-dn1 2.0a.

## 7. Verified vs pending

Verified: compiles clean, links/patch byte-verified (sections 2/4/5/6/7/8),
digiemu boot/settle (`dsp_running=2`), all six FX pages present
(`kinds=[16,15,17,0,1,2,3,4,5]`) and the PERFORM page (kind 6,
`kinds=[16,15,17,0,1,2,3,4,5,6]`), hardware boot + first manual pass working.
The PERFORM page is verified live (real SSI renders): UP enters it, an encoder
raises the pattern value, and each engine's pads move only their own depth and
restore on release (ring 51→70→51; fold 0→63; crush 0→63; WAVE pitch 64→79;
WAVE stereo 64→111, with the other depth unchanged). Store v8 round-trips.

Pending:
- **CPU headroom** — render-vector worst/p99 cycles and deadline margin
  (`emu.cftiming.deadline_report`) not yet captured; the full
  `emu.portable --check --timing` run was aborted.
- **DSP (Core B)** — untouched by the suite; its render is not part of the FX
  budget.
- **dB** — peak/RMS with FX off vs on not yet measured.
- **CC 20–31** — not checked against the stock CC table (`0x4018D104`).

## 8. Future footprint work

1. **Fuse the six master passes** into one loop (§4.15): order-of-magnitude
   fewer loads/stores per frame.
2. **Use the EMAC** for the Q15 multiplies (`dn_mul15`/`dn_mul14` are two muls +
   shifts; the EMAC does an exact 32×32→64 MAC in one op). The core already
   saves/restores EMAC; leave `MACSR` as found.
3. **Trim SHFT further**: nearest-neighbour on the second grain (drop 2–4 interp
   muls), optional by knob/flag; the crossfade is already one mul per channel.
4. **Meter**: gate on page visibility (`dc_vis`) and fold peak detection into
   the fused loop.
5. **Loop-level**: unroll 2–4 frames; align the delay line and tables
   (`__attribute__((aligned(16)))`).
6. **`.fast` SRAM**: blocked — the DN device profile claims no `.fast` area and
   the render block is not self-contained (`docs/FAST-AUDIO-DN.md`).
7. **Reconsider `-O3`** only if a measured render-margin win appears.
8. **Shrink the delay line** (the 16 KB DDR allocation is the biggest cost, and
   DDR accesses cost more than the instruction count implies). Trade quality for
   footprint/CPU, best for lo-fi modes: **downsample** the line (one write per 2
   samples, interpolated reads → half the writes/DDR traffic), **cap to 12 bits**
   (`int16` line → ~8 KB, big quantization on the 24-bit bus), or **shorten
   `WV_N`** (2048 → 1024, ~21 ms is plenty for WOB/FLAN/SHFT). Measure with a
   bounded `gui.snap` + `emu.cftiming` pass. The flush/prime in §6 (flanger
   residue) and this can be done together.

## 9. perf-opt branch ledger (experimental, `digitone_corea_perf`)

One row per landed item, in `perf:` commit order. Baseline is `tonefx 3.5d`
(`.run 26863`, `.bss 25562`, 11 sites, **917** relocs, `imports nothing`). The
win must be **measured**, not assumed; nothing here is released — the release
repo (`Tone+FX`) is cut from `main` only.

| # | item | method | `.run` | `.bss` | relocs | behaviour | status |
|---|---|---|---|---|---|---|---|
| 1 | Direct framebuffer UI drawing | `dg_px`/`dg_fill` write the 1 bpp panel bytes at `fb_front` (`0x40241a44`) directly, in the stock coordinate frame (display row `63-y`); all page graphics (glyphs, dots, spans, clears) stop calling `DN_FILLRECT` | 26863 → **26707** (−156) | 25562 → 25566 (+4) | 917 → 908 | RING/FOLD/TILT screenshots **pixel-identical** | **landed** |
| 4 | Meter gated on visibility | `digimeter_render_out` returns unless `digictl_meter_active()` — a weak hook (undefined in a standalone meter build) that is true only while the FOLD page, the sole reader of `digimeter_l/r`, is up | 26707 → **26791** (+84) | 25566 → 25570 (+4) | 908 → 915 | FOLD/RING/TILT screenshots identical; render worst −408 cyc | **landed** |
| 11 | Hoist per-sample block-constant branches | Split `crush` BITS into dither / no-dither loops and `fold` into drive / no-drive loops (GCC does not loop-unswitch at `-O2`); when a section is bypassed its loop is unchanged | 26791 → **26983** (+192) | 25570 | 915 | fold+crush output bit-identical by construction; pages unchanged | **landed** |
| 5 | Ceiling gated on "hot" | `digictl_limit_out` returned unless `dn_fx_hot()` — **REVERTED (audible)**: with every section off the raw mix can still exceed the knee, and skipping the limiter then hard-clips, so the limiter must run every block | 26983 → 27155 (+172) then **reverted** | 25570 | +13 then reverted | clipping heard on hardware when FX off | **reverted** |
| 14 | Store-sync gating | `dn_store_sync` / `dn_store2_sync` compare the block only every 8th UI tick (dirty writes and pattern switches still immediate); the adopt guard still runs, ≤ 8 ticks later | 27155 → **27199** (+44) | 25570 → 25578 (+8) | 930 → 934 | pattern-store test PASS | **landed** |

**Item 1 detail.** Before: `digictl.c` had **36** `DN_FILLRECT` call *sites*; the
per-pixel glyph path (`dg_glyph`, used by every 2x mode name and the `<`/`>`
arrows) and the dot/span loops meant **dozens of firmware calls per frame** (each
a 6-argument call); every lit glyph pixel was also a 2x-scaled fill (4 writes).
After: **0** `DN_FILLRECT` sites, all page graphics are byte writes; only the
single slider `DN_FRAMERECT` (kept for exact corner parity) and the `DN_TEXTF`
strings remain. The scaled glyph names cost 21–34 calls each (MUD 22, CLEAN 29,
TRSH 32, SHFT 34); the dot graphics another ~16–57 (PITCH 52, macros ~28–56).
Verified by `tests/digiemu_fx_screenshots.py` against `dn1-35p1-f001f93a`:
RING/FOLD/TILT byte-identical to the `3.5d` baseline PNGs.

**Item 4 detail.** The meter's per-block peak scan (32 frames × ~2 loads + abs +
cmp ≈ **~450 cycles** of the render vector) ran on every page though only the
FOLD page ever draws the bars. `digictl` now exports `digictl_meter_active()`
(true only while `cur_kind == DN_FEKIND` and the view is live); `meter.c` holds
it by a **weak** reference, so a standalone `digimeter` build still links and
just runs as before. Measured with a bounded `cftiming` pass
(`accel=max`, audio on, default page, 300 ms; render vector):

| | worst cyc | p99 cyc | mean cyc | deadline margin |
|---|---|---|---|---|
| `3.5d` (meter scans) | 99965 | 99958 | 99543.1 | 0.4003 |
| meter gated | **99557** | **99550** | **99140.8** | **0.4027** |

The −408-cycle worst/p99 and +0.24 pp margin are the skipped scan; on the FOLD
page the scan still runs, and the FOLD screenshot is byte-identical to `3.5d`.

**Item 11 detail.** `crush` BITS tested `if (dith)` every sample and `fold`
tested `if (dg)` every sample, both block-constant. Splitting each into two
specialized loops removes 32 branches per block and lets the simpler variant
(the `p &= mask` loop; the fold-only loop) schedule tighter. Measured with a
bounded `cftiming` pass and the FX forced on (`fold` TRSH amount 100, `crush`
BITS amount 100 tune 40; addresses poked from `testout/*.map.json`):

| | worst cyc | p99 cyc | mean cyc | deadline margin |
|---|---|---|---|---|
| `3.5d` loops | 104579 | 104565 | 104152.7 | 0.3726 |
| split loops | **104158** | **104158** | **103707.7** | **0.3751** |

−421-cycle worst and +0.25 pp margin for +192 B of `.run` (flash spare ~1.68 MB,
RAM unchanged). Output is bit-identical (same operations, reordered into two
loops); the bypassed path returns before either loop, so inactive blocks are
unchanged.

**Item 5 detail.** The output ceiling looped all 32 frames every block. It only
matters when a section can push the mix past its knee; when nothing is hot it is
a no-op (the factory pattern peaks near `2^21`, well under the `0x600000`
knee), and the stock OS has no ceiling at all — so skipping it is exactly the
raw mix the stock code always produced. `dn_fx_hot()` is conservative (ring
depth, EQ off-flat, fold/crush amount, any WAVE mode, any macro). cftiming, all
FX forced neutral:

| | worst cyc | p99 cyc | mean cyc | deadline margin |
|---|---|---|---|---|
| always limit | 96086 | 96086 | 95682.2 | 0.4235 |
| gated | **95140** | **95140** | **94701.2** | **0.4292** |

−946-cycle worst, +0.57 pp. With the default FX (ring + EQ hot) the limiter
still runs: render worst 99557 → 99572, margin 0.4027 → 0.4026 (the ~15-cycle
hot-check, negligible). Pages unchanged.

**Item 5 detail — REVERTED.** The gate was **not** inaudible: with every section
off the raw mix can still exceed the `0x600000` knee, and skipping the limiter
lets it reach 24-bit full scale and hard-clip — heard on hardware as distortion
when the FX are switched off, curing when a section is switched back on (its
flag re-arms the limiter). The "no audible change" rule wins over the ~950-cycle
clean-path saving, so `digictl_limit_out` runs every block again. The plan's
"audio: none" rating was wrong for this item.

**Item 14 detail.** Each UI tick compared 84 bytes (store1 64 + store2 20) against
its shadow. The compare now runs every 8th tick when nothing is pending and the
pattern pointer has not moved; a dirty page edit and a pattern switch are still
handled immediately, and the adopt guard (a stock write onto our block) is
detected within 8 ticks. Measured over a 1 s session: instructions
152,786,675 → **152,760,808** (−25,867, ≈ the 7/8 of the compare loops removed);
cycles neutral in `cftiming` (the removed loads/compares overlap the tick's
stalls), so this is an instruction/bus-read win, not a cycle one. Persistence
verified: `tests/digiemu_pattern_store.py` PASS (`DGX1` magic and marker survive,
per-pattern switch works).

## 10. Feature / fix work on this branch

Not optimizations; landed here because they touch the same files.

### 10.1 Flanger/pitch linked delay — fixed (HANDOFF §6, paired with #12)

**Bug:** WOB / SHFT / FLAN shared one delay line `wv_buf`; FLAN writes its
*fedback* output into it, so leaving FLAN left ~16 ms of feedback samples that
WOB/SHFT then read and distorted the PITCH bloc.

**Fix (HANDOFF §6 option 2/3):** FLAN now owns a **separate** line
`wv_fbuf[2][WV_FN+1]` (`WV_FN` 256 ≈ 5.3 ms — enough for FLAN's base 128 + span
127); WOB/SHFT keep the dry line `wv_buf`. They can no longer cross-talk, so no
transition flush is needed for correctness. **Paired with #12:** the dry line is
now `WV_N` 2048 → **1024** (~21 ms — still > the 765-sample WOB delay and the
~756-sample SHFT grain), which is the delay-line footprint win.

| | before | after |
|---|---|---|
| `.bss` (delay lines) | 25578 | **19446** (−6132) |
| `.run` | 27199 | 27595 (+396 incl. the OFF cue) |

**Verified** (`flanger_check.py`, silent snapshot, sentinel-seeded lines):
FLAN moved only its own line (`wv_fbuf` changed, `wv_buf` byte-identical to the
sentinel); WOB moved only the dry line (`wv_buf` changed, `wv_fbuf` untouched).
**Trade:** SHFT's grain history is 1024 instead of 2048 samples; WOB is
unaffected. Confirm the SHFT sound on hardware.

### 10.2 OFF cue on the FX / macro pages

Every DIGI page whose section is switched off now draws an `OFF` message box
(1 px frame + `OFF`, centred horizontally above the middle of the drawable area)
over the page: RING/FOLD/TILT/CRUSH/PITCH/STEREO by their on flag, WASH/RADIO/
DESTROY/SPACE by their macro flag. PERFORM has no on/off and shows none. Drawn
with the direct-framebuffer helpers (#1) after the page. Verified by capturing
all 11 pages: the off-by-default CRUSH/PITCH/STEREO/WASH/RADIO/DESTROY/SPACE
show the box; RING/FOLD/TILT do not.

### 10.3 FLAN never truly bypassed — fixed (the "distortion after switching FLAN off")

The real cause of the flanger-related distortion (separate from the shared delay
line, §10.1) was a bookkeeping bug in the FLAN ramp: at the end of the FLAN loop
the engine did `wv_fla_mix = mix;`, storing the **target** (`digiwave_mix*258`)
instead of the ramped local `m`. Every other mode stores the ramped local
(`wv_wob_wet = wet`, `wv_shf_wet = w`, `wv_pan_dep = dep`, `wv_wide_cur = d`).
Because `wv_fla_mix` was reset to full mix every block, switching FLAN off made
`m` restart at full mix and sweep to 0 **within every block** — a ~1.5 kHz
flanger buzz that never reached the `m_t == 0 && m == 0` true-bypass return. It
stopped only when the active WAVE group was changed (editing the PITCH page),
which is why toggling PITCH "fixed" it.

Fix: `wv_fla_mix = m;`. Verified with the symbol map: FLAN on →
`wv_fla_mix` 25792 (target 25800); FLAN off → **0** (was stuck at the target
before). With this and §10.1, switching FLAN off now bypasses cleanly.

### 10.5 Macro layer: cue when an FX page is macro-driven; macro-off leaves engines on

**Bug (build 3.5q):** the macro pages (`WASH/RADIO/DESTROY/SPACE`) capture the
engines' settings when the first macro turns on (`mw_capture`) and restore them
when the **last** turns off (`mw_restore`). `mw_apply` only restored when **no**
macro was left on, so switching `WASH` off while e.g. `RADIO` was still on left
`WASH`'s contributions (the WAVE WOB wobble) running — the "OFF toggle does not
deactivate the FX completely" symptom.

**Fix:** `mw_apply` now rebuilds the layer from the captured base **every block**
(`mw_restore()` then each active `mw_one()`), so turning any macro off drops
exactly its engines while the others stay. Verified: WASH on → `digiwave_on=1,
pmode=WOB, pdepth=100`; WASH off with RADIO on → `digiwave_on=0` (WAVE released);
all off → the pre-macro base restored.

**Cue:** a page whose FX is being driven by a macro now draws a **`MACRO`** box
(framed, top-right — the same style as `OFF`) so it is clear the page's encoders
are locked. `dg_page_locked(k)` maps each FX page to the macro(s) that drive it
(ring←DESTROY; fold←RADIO|DESTROY; EQ←WASH|RADIO; crush←WASH|RADIO|DESTROY;
WAVE pitch←WASH; WAVE stereo←SPACE). `OFF` takes precedence only if no macro is
driving the page.

### 10.6 Control/stock-param conflict audit (3.5q)

Our `ev_key`/`ev_enc` handlers are the only place the suite sees stock input, and
they are deliberately narrow:

- they run only while the **master view is open and recently drawn**
  (`master_live`: `dc_vis>0` **and** the view's closed byte `view+0x30 == 0`),
  so a closed background view cannot keep them armed (the MIDI-track microtiming
  / encoder-leak fix, §10.4);
- `ev_enc` consumes an encoder **only on our pages** (`cur_kind` in 0..10);
  on a stock page it returns 0 and the stock parameter edit proceeds;
- `ev_key` consumes only our keys: the 16 trigs are pads **only on PERFORM**,
  `UP` is consumed **only on our pages**, and `LEFT/RIGHT` rotate the master page
  list while the view is ours. **`PAGE` (19) and every other key are never
  consumed** — they always reach the stock OS.

So on our pages the stock does not see the encoders/keys we own, and on stock
pages we do not see them. The remaining stock-side oddity
(`PAGE` jumping some FX levels) is the separate HANDOFF §8 item, not a control
conflict.

### 10.4 Key/encoder handlers stayed armed after the master view closed (HANDOFF §8)

**Bug:** `digictl_key` / `digictl_enc` gate on `master_live()`, which only tested
the view's vtable plus the decaying `dc_vis` countdown, and `digictl_tick`
re-invalidated the view while `dc_vis > 0`. A closed-but-still-allocated master
view therefore kept consuming LEFT/RIGHT (and UP/trigs), so in the sequencer
"hold a trig + arrows" microtiming did not nudge, and encoder turns leaked
(volume jumps) — HANDOFF §8 item 3.

**Fix:** the DN view object carries a **"closed" byte at `view + 0x30`** —
`view_activate` clears it (`0x400e53da`) and `view_close` sets it
(`0x400e51e6`). `master_live` now requires `*((unsigned char *)v + 0x30) == 0`,
and `digictl_tick` stops invalidating (and forces `dc_vis = 0`) once the view is
closed. Verified: with the view open RIGHT rotates the pages; with `+0x30 = 1`
(simulated close) RIGHT no longer touches the index and the tick disarms.
