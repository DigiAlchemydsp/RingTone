# ToneFX-BufferFX — optimization round (0.2w → next)

Measured on the 0.2w build with the bounded `cftiming` probe
(`tests/_timing_buffx.py`, one Session, `accel=max`, 120 ms/slice). The render
budget is **166,667 cycles per 667 µs block** at 250 MHz. "Cost" is the engine's
added **worst-case cycles per block** over the stock render; "headroom" figures
are cycles/block freed (measured where marked, else estimated from the loop
structure). Hardware may differ from the emulator's cycle model.

## 0. Measured baseline (0.2w)

| config | worst cyc/block | margin | late |
|---|---|---|---|
| all-off (stock + keepalives) | 101,321 | 0.392 | 0 |
| WRMZ on | 109,990 (+8,669) | 0.340 | 0 |
| Grainz on | 120,938 (+19,617) | 0.275 | 0 |
| Tailz on | 147,138 (+45,817) | 0.117 | 0 |
| **all three** | **160,038 (+58,717)** | **0.040** | 0 |

Takeaways:
- **Tailz dominates** (~78 % of the all-on worst case). Optimise it first.
- **All three leave only 4 % of the block spare** (≈6,600 cycles) at worst. The
  p99 is better (Tailz p99 128.7k), so it is the *worst* outlier that is thin;
  one more heavy stage would not fit.
- Even "all-off" carries ~4 stores/frame of keepalive (WRMZ+Grainz push their
  lines while off); that is inside the 101,321 baseline.

RAM: `.bss 892,334` of the 1.25 MB pool (372,268 B spare): WRMZ line 524 KB ·
Grainz history 262 KB · Tailz ~102 KB.

---

## 1. Optimizations, with headroom and counterpart

Ranked by headroom. "Cost/counterpart" is what you pay or risk for it.

### Tailz (the heavy one)

| # | optimization | headroom | counterpart / cost |
|---|---|---|---|
| T1 | **Power-of-two line lengths** — replace the two `if (ri >= len) ri -= len` compares per line read (×8/frame) with a single `& (len-1)` mask | est **−3…5 k** | Line lengths become powers of two, so rooms lose the mutually-prime spread (a little more comb/colour) and SIZE snaps to coarse steps. Deterministic, low risk. |
| T2 | **6 FDN lines (from 8)** — the read/damp/write loop is ~linear in lines | est **−11 k** | Thinner tail; the four diffusion allpasses carry most of the density loss (this is what the recreation's 4-line room leaned on). A/B needed. |
| T3 | **4 FDN lines (from 8)** | est **−23 k** | Metallic/boxy at small sizes; only with more diffusion. Big change to the sound. |
| T4 | **Damp a subset of lines** (e.g. 4 of 8, or one shared damping state) — drop half the one-pole muls | est **−2…3 k** | Brighter/less tail control; per-line damping is what shapes the low end. |
| T5 | **Fewer diffusion allpasses** — default DIFF lower, or gate `nd` to ≤2 | est **−2…3 k** | Sparser early reflections at low DIFF. The DIFF knob already gates cost; only the default/heavy case changes. |
| T6 | **Skip the pre-delay line when PRE = 0** (use the input directly) | est **−1…2 k** | None while PRE=0; a knob move must re-prime the line (one block). Free headroom for the common case. |
| T7 | **Unroll the 8-line loop into named locals** (drop the `y[8]`/`rv_lp[]` array traffic) | est **−2…4 k** | Code size up; GCC may already be near register pressure, so measure — could also regress. |
| T8 | **Flat, 16-byte-aligned line buffer** read/written with a pointer | est **−1…2 k** + cache | None; just a layout change. |
| T9 | **Run the FDN at half rate** (sample every other frame, interpolate) | est **−20 k** | Halves reverb bandwidth; a low-pass/aliasing character. The biggest single win, and the biggest sound change. |

### Grainz

| # | optimization | headroom | counterpart / cost |
|---|---|---|---|
| G1 | **Nearest-neighbour grain reads** (drop the interpolation load+mul per head) | est **−6…8 k** | Grain grit/aliasing — explicitly acceptable for a granular character (the recreation's SPLASH used nearest for exactly this). |
| G2 | **3 heads (from 4)** | est **−5 k** | Thinner cloud / less overlap at high DENS. |
| G3 | **Per-head window via a 256-entry Hann table** (replace `sin²`) | est **−0.5…1 k** | None (a table adds ~512 B `.run`). |
| G4 | **Skip the head loop when no grain is active** (hoist the "any head on" flag) | est **−0.5 k** | None. |

### WRMZ

| # | optimization | headroom | counterpart / cost |
|---|---|---|---|
| W1 | **Hoist the ENSEMBLE branch out of the per-frame loop** (two loops) | est **−1 k** | None; more code. |
| W2 | **Nearest reads** for the swept delay (drop the interpolation mul) | est **−3…4 k** | Quantised delay → zipper/aliasing while modulating. Use only in TAPE/BBD if at all. |
| W3 | **Cheaper DC/feedback path** (leaky integrator instead of the 2-state DC blocker) | est **−2 k** | Slow DC buildup possible at high FB; the saturator already bounds it. |
| W4 | **½-size line (2^17 → 2^16)** | RAM **−256 KB**; maybe small CPU via cache | Max delay 2.73 s → 1.37 s. |

### Cross-cutting

| # | optimization | headroom | counterpart / cost |
|---|---|---|---|
| X1 | **Gate the off-state keepalive** (WRMZ/Grainz push only for N blocks after disable, then stop) | est **−2…4 k** (off-state only) | A stale/silent buffer if re-enabled after the window (a short pre-roll of old/quiet audio). |
| X2 | **Fuse the three new passes into one loop** (load L/R once, run all three inline, store once) | est **−5…10 k** | Register pressure is already high (8-line FDN + 4 heads) — likely spills, could regress. **The suite's fused core insert measured +15 % on hardware, so verify on hardware, not just emu.** |
| X3 | **Use the EMAC** for the Q15 multiplies (FDN feedback/damping, feedback gain): 32×32→64 in one op vs 2 muls+shifts | est **−5…15 k** across engines | Must leave `MACSR` as found (the core saves/restores it around the render); real complexity; the suite parked this. Biggest structural win if it lands. |
| X4 | **Move the buffers to a claimed `bulk` region (Tier 1)** | RAM **−892 KB** of the pool | Region claim → no longer a drop-in beside an overlapping region mod (DigiCosm/DigiChroma); needs an incremental clear + `*_ready` gate (OS never clears `bulk`). Frees the pool, **not** CPU — only do it if code/other mods need the RAM. |
| X5 | **16-byte-align all lines** | maybe small CPU via cache | None; a single attribute. |
| X6 | **Half-rate / 12-bit line storage** | RAM −50 % (WC), CPU flat | Bandwidth/noise loss; not a CPU win. |

---

## 2. Recommended sequence

Keep the sound stable and buy the headroom where it is cheapest first:

1. **T1 + T6 + W1 + G3/G4 + X5** — mechanical, near-lossless (~7–10 k, mostly Tailz). No audible change intended; A/B to confirm.
2. **G1 (nearest grain reads)** — ~7 k, accepted granular trade.
3. **T2 (6 lines) + T4 + T5** — ~14 k, the main reverb trade (A/B the room).
4. **X1** — a few k in the off state.
5. **X3 (EMAC)** — the structural win, if the `MACSR` discipline is proven on hardware.
6. **X2 (fuse)** — only with a hardware timing check; treat as experimental.
7. **T8/X4** — layout/RAM only; X4 last (compatibility decision).

Target after step 3: all-three worst back under ~130 k (**margin ≥ 0.20**), with
no audible change to WRMZ/Grainz and a deliberate, verified reverb trade.

## 3. How each is verified

- **CPU**: re-run `tests/_timing_buffx.py` after each change; the per-engine delta
  must match the estimate; watch the all-three margin and `late == 0`.
- **Sound**: the live diag (`tests/_diag_buffx_live.py`) for 0 faults; an audible
  A/B (same pattern/notes, engines at fixed settings) for the trade items
  (T2/T3/T4/T9/G1/G2/W2).
- **Hardware**: at least one hardware pass on the heaviest setting (all three on)
  after the sequence — the emulator under-reports the insert-fusion penalty.

> Measurement is emulator `cftiming` (`accel=max`); it is a bounded sample, not
> the full `emu.portable --check --timing` audit. Treat cycle figures as ±10 %.

---

## 4. Applied (0.3w) — what was done and the measured result

Implemented from the list above:

| item | change | result |
|---|---|---|
| **T3** | Tailz **8 → 4 FDN lines**, Householder `y - sum/2` (a shift, no divide) | the big Tailz cut |
| **T1′** | unipolar line modulation → **one wrap compare** per line read (was two) | — |
| **T6** | Tailz **skips the pre-delay line when PRE = 0** (the default) | — |
| **G1** | Grainz **nearest-neighbour grain reads** (no interpolation) | grain grit accepted |
| **G2** | Grainz **4 → 3 heads** | — |
| **W2′** | WRMZ **nearest read when the delay is static** (span 0) | quality kept when modulating |
| **X5** | big lines **16-byte aligned** | — |
| RAM | WRMZ line 2^17 → 2^16 · Grainz history 2^16 → 2^15 · Tailz line 4096 → 2048 & pre-delay 8192 → 4096 | **`.bss` 892,334 → 441,770 (−440,564 B)** |

**Measured (same probe, `accel=max`, 120 ms/slice):**

| config | 0.2w worst | 0.3w worst | 0.2w margin | 0.3w margin |
|---|---|---|---|---|
| all-off | 101,321 | 101,247 | 0.392 | 0.393 |
| WRMZ | 109,990 | 109,410 | 0.340 | 0.344 |
| Grainz | 120,938 | 119,285 | 0.275 | 0.284 |
| Tailz | 147,138 | 130,163 | 0.117 | 0.219 |
| **all three** | **160,038** | **138,848** | **0.040** | **0.167** |

- Tailz cost **+45,817 → +28,916 (−37 %)**.
- All-three margin **0.040 → 0.167** (4.2×); still `late 0`.
- RAM spare **372,268 → 822,164 B**.
- Build: `.run 40,739`, `.bss 441,770`, `imports nothing`; boots/settles; live diag
  0 faults.

### Still on the table (not applied)

- **T9 half-rate FDN** (−~20 k) and **Grainz 2 heads** (−~5 k): real headroom, but
  audible trades (halved reverb bandwidth / thinner cloud). Do deliberately.
- **T4 damp fewer lines**, **T7/T8 unroll/flat line**, **X1 gate keepalive**: small.
- **X2 fuse the three passes** and **X3 EMAC**: structural, need a hardware timing
  check (the suite's fused insert measured +15 % on hardware).
- **X4 move buffers to a `bulk` region**: RAM only (the pool is no longer tight),
  and a compatibility cost — defer.

**Deliberate sound trade in 0.3w:** Tailz is now a 4-line room (the recreation's
design). It leans on the four diffusion allpasses for density; A/B it against the
8-line 0.2w room and decide whether to keep 4, or take 6 with a `/3` Householder.

---

## 5. Deeper round (0.4w) — mono + half-rate, and the Grainz click fix

The user reported Grainz clicks and CPU still saturating, and authorised quality /
stereo trades (they widen externally). Applied:

| item | change |
|---|---|
| **Mono WRMZ** | one s16 line (was stereo L/R); wet is mono, mixed into both channels; dry stays stereo |
| **Mono Grainz** | one s16 history; cloud mono; one read per head (was two) + interpolation restored |
| **Half-rate Tailz** | the FDN/diffusion/pre-delay run every other frame, the wet held across the pair |
| **Grainz click fix 1** | a grain's span (`len × rate` frames) is placed **behind** the write head, so it never reads unwritten history (the read-past-the-head discontinuity) |
| **Grainz click fix 2** | when all heads are busy a spawn is **skipped** instead of stealing a live head mid-window (the abrupt cut) |
| RAM | mono halves the lines: `.bss` **441,770 → 245,098 (−196,672 B)** |

**Measured:**

| config | 0.3w worst | 0.4w worst | 0.3w margin | 0.4w margin |
|---|---|---|---|---|
| all-off | 101,247 | 101,330 | 0.393 | 0.392 |
| WRMZ | 109,410 | 106,375 | 0.344 | 0.362 |
| Grainz | 119,285 | 114,307 | 0.284 | 0.314 |
| Tailz | 130,163 | 121,533 | 0.219 | 0.271 |
| **all three** | **138,848** | **127,414** | **0.167** | **0.236** |

Cumulative over 0.2w: **margin 0.040 → 0.236 (5.9×)**, `.bss` 892,334 → 245,098
(−647 KB), all-three worst 160,038 → 127,414 (−32,624 cycles). `imports nothing`,
both OS builds byte-verified, boot/settle + live diag 0 faults.

### Trade ledger since 0.2w (all deliberate)

- **Mono wet** for WRMZ / Grainz / Tailz — the effect is centred; widen on the
  mixer/DAW. The dry stays fully stereo. This is the single biggest RAM/CPU win.
- **Half-rate Tailz** — the reverb is band-limited to ~24 kHz (a low-pass on the
  tail). No decimation filter, so a little aliasing on very bright content.
- **4-line Tailz room** — smaller/denser than 0.2w's 8-line room.
- **3-head Grainz** — sparser cloud; no steal means grains simply don't spawn
  when the pool is full (density self-limits instead of cutting).

### Further levers (not applied)

| lever | headroom | trade |
|---|---|---|
| Grainz 3 → **2 heads** | ~−4 k | sparser cloud |
| Tailz **3 lines** (`sum × 10923 >> 15`) | ~−5 k | thin/boxy room |
| Tailz diffusion default → 2 allpasses | ~−1 k | sparser early reflections |
| **EMAC** for the Q15 muls | ~−5…15 k | no quality loss; MACSR discipline + complexity |
| Fuse the three passes (one loop) | ~−5…10 k | register spills; **verify on hardware** |
| Move buffers to a `bulk` region | RAM only | loses drop-in compat |

The remaining all-three cost is ~26 k cycles over stock; Tailz is ~20 k of it. If
more is needed, the next safe step is **EMAC** (no sound change), and the next
audio step is **2-head Grainz** and/or **3-line Tailz**.

### 5.1 Bug found and fixed: the Tailz half-rate off-by-one (a 1.5 kHz buzz)

The first 0.4w half-rate loop read the second frame's dry from `p[4],p[5]`
instead of `p[2],p[3]`. For the upper output half that index is 256 bytes past
the audio buffer (into the param frame), so the block's **last sample** was
written from out-of-bounds memory every block — a **constant ~1.5 kHz buzz** the
user heard as "Tailz is completely broken". A silent-input level probe
(`tests/_probe_tailz.py`) showed one nonzero sample (47,616) at buffer index 127
and the FDN state at zero, which pinpointed it. Fixed to read `p[2],p[3]`;
re-probed: output 0 with a silent input, no buzz, live diag 0 faults. (The probe
and the fix are in `mods/digtailz/tailz.c` / `tests/_probe_tailz.py`.)

> Note: the current tree is **0.9x** — one delay module (`wrmz.c`, WRMZ +
> GRAINZ modes); Tailz/Grainz-as-separate-module are gone. The 0.2w–0.4w numbers
> above are kept as the reverb-history ledger.

---

## 6. eMAC round — applied (current 0.9x tree)

The delay engine's per-frame gains now run on the MCF5441x's **eMAC** (item
**X3** in §1). GCC does not emit EMAC instructions (verified: GCC's m68k
machine description says so), so `src/emac.h` supplies them as inline asm.

- In signed-fractional mode (MACSR = `0x20`) the eMAC evaluates
  `movclr.l( mac.l Y,X ) == (Y*X) >> 31` exactly. With multiplicand `X = c<<16`,
  `(x*(c<<16))>>31 == (x*c)>>15` — i.e. `dn_mul15` in **one `mac.l`** (was two
  `muls.l` + two shifts + add). `bx_mul12` is the same with `c<<19`.
- The core saves/restores the whole EMAC around the audio render, so the handler
  **saves `MACSR` on entry, sets `0x20`, restores it before every return path**
  (`bx_macsr_save/frac/restore`); `movclr` leaves `ACC0` zeroed. No `return`
  between save and restore; the off/true-bypass path touches neither.

Applied in `wrmz.c`: the five per-frame gains — dry/wet mix (L and R), feedback,
the tone one-pole (`bx_lp_e`) and the DC blocker (`bx_dc_e`).

**Suite-wide (same round).** The same helpers now cover the always-on and
active suite stages:

- `ring.c` — the carrier interpolation (`bx_mul8`) and both depth multiplies
  (`bx_mul15` ×4/frame).
- `eq.c` — both band gains (`bx_mul14` ×4/frame); Q14 coefficients are small
  (≤ 8192).
- `wave.c` — WOB / FLAN / SHFT / PAN (`bx_mul15`, incl. `wv_read`); WIDE stays C.
- **`fold.c` / `crush.c` are *not* converted:** their multiply is a **Q8 gain
  that exceeds 1.0** (up to ~4×, `gain` 256…1272). The fractional eMAC resolves
  `(x*c)>>k` only for `|c| < 2^k`, and `c` up to 4× overflows the `c<<(31−8)`
  multiplicand, so it would need an unsafe `x<<8` pre-shift on a bus that is not
  provably ≤ 2²³ mid-chain. Left as C; the Q8 drive is active-only anyway.

| | baseline 0.9x | + eMAC `wrmz` | + eMAC suite |
|---|---|---|---|
| `.run` | 33,698 | 33,522 | **32,810** |
| `.bss` | 85,110 | 85,110 | 85,110 |
| relocations | 1,183 | 1,182 | 1,183 |
| all-off (cyc/block) | 99,682 | 99,674 | **98,494** |
| WRMZ (margin) | +8,521 (.351) | +7,106 (.359) | **+7,064 (.367)** |
| GRAINZ (margin) | +11,399 (.334) | +10,102 (.341) | **+10,081 (.349)** |

The always-on baseline drops **−1,188 cyc/block** (ring is on by default; EQ
bypasses when flat, so its eMAC only pays when the user moves it). The delay
engine is **−16.6 % (WRMZ), −11.4 % (GRAINZ)**. `late 0`; `imports nothing`.
Same clock for all builds (bounded `cftiming`, `accel=max`, 120 ms/slice);
treat as ±10 %.

**Verified.** The primitives are **bit-exact** against the C forms over the full
input domain (negatives, ±2²⁴, multiples of `2^k ± 1`, random; Q15/Q14/Q12/Q8)
under the patched-Unicorn CFV4E EMAC model — 0 mismatches. `lint` + `patch`
byte-verified on OS 1.43 and 1.44; digiemu boot/settle (`SETTLED 1450M`,
`dsp_running_u32=2`); live diag (WRMZ + GRAINZ, real SSI renders) 0 faults.

**Files:** `src/emac.h` (new), `mods/digiwrmz/wrmz.c`, `mods/digiring/ring.c`,
`mods/digieq/eq.c`, `mods/digiwave/wave.c`.
**Artifacts:** `mods/tonefx-buffx/out/tonefx-buffx-0.9x[-os1.44].elemod`
(sha `08a2e416…`), `testout/tonefx-buffx-suite-emac-1.43.syx` / `-1.44.syx`;
stage baselines `testout/ab-baseline-1.43.syx` (sha `6933664d…`) and
`testout/tonefx-buffx-opt-1.43.syx` (wrmz-only, sha `523ce62f…`).

### Still on the table after this round

| lever | where | headroom | note |
|---|---|---|---|
| eMAC on wrmz's remaining muls | WRMZ `bx_read_at` interp (mod>0), GRAINZ `/3` | small | `bx_mul12` exists; `/3` = `bx_mul15(x,10923)` |
| `fold`/`crush` Q8 drive | fold, crush | small (active-only) | needs a wider-Q8 form (byte-split) or an `x` pre-shift with a proven bound |
| 4-accumulator MAC | heaviest loops | small–med | 2 frames (or L/R pairs) in flight to fill the MAC pipeline |
| `bfffo` for the meter log2 | `meter.c` `dm_bar` | tiny | one ISA-C instruction replaces the `while(peak>1)` shift loop |
| P0 `bulk` region / P1 shrink / P2 trim | see HANDOFF §2 | boot RAM, not CPU | unchanged |

---

## 7. Coeff / range / UI round (0.9x +eMAC +r2)

Sandboxed work on the current tree, driven from the hardware ear-test: mix
sliders distorted at max, delay modulation too fast, PITCH/STEREO still shared a
rate, and the RING/DELAYS pages needed the suite's layout.

### 7.1 Mix distortion at max — soft-clip the feedback paths
The mix crossfade was correct (`l + m*(wet-l)`, `m <= 32767`); the distortion is
the **feedback headroom**. The s16 delay line (`wrmz.c`) hard-clipped
`bx_sat16(mono + fb*lp)` at FB up to 0.80, and STEREO FLAN hard-clamped its
feedback at `0x700000`. Both now go through **`bx_soft(x,T)`** (`buffx.h`): linear
to the knee (3T/4), half slope to a hard stop at T — a hot 100%-wet sum
compresses instead of clipping. Transparent below the knee.

### 7.2 Modulation ranges — sub-Hz LFO
WRMZ `RAT` and GRAINZ `DEN` were `1+f*9/127` = **1..9 Hz**; WAVE `SPD` was
**1..12 Hz**. All now use a **milli-Hz** phase increment (`bx_inc_mhz`):
WRMZ/GRAINZ **0.1..3.0 Hz** (`100 + v*2900/127`), WAVE **0.1..5.0 Hz**
(`100 + v*4900/127`). Slow enough for wow/drift.

### 7.3 PITCH / STEREO decoupled
`digiwave_speed` was one variable for both groups (+ PERF). Split: PITCH keeps
`digiwave_speed`, STEREO gets **`digiwave_sspeed`** (wave engine, PITCH page enc
5 / STEREO page enc 5, `dg_stereo_gfx`). STEREO speed is a stored param: **DGX2
v2 → v3** (7 → 8 params); new MIDI **CC 32** (stereo speed). Old DGX2 blocks fail
the version check and adopt live values (documented).

### 7.4 eMAC across every block (CPU)
`src/emac.h` now also carries **`bx_mul14w`** (WIDE's `d*256`) and **`bx_q8`**
(byte-split Q8 drive). Applied:
- `fold.c` / `crush.c` — the Q8 fold/drive gains (`bx_q8`, exact).
- `wave.c` — WIDE (`bx_mul14w`), on top of the WOB/FLAN/SHFT eMAC from §6.
- `meter.c` — `dm_bar` log2 via ISA-C **`ff1`** (leading-zero count) instead of
  the shift loop.

Verified bit-exact: Q15/Q14/Q12/Q8 via patched-Unicorn; `bx_q8`/`bx_mul14w`
algebraically over their domains (0 mismatches).

### 7.5 UI
- **RING** (`dg_fx_page`): the animated circle moved to the **left third**
  (`cx=20`), with a bold screen-centred **`dg_bigname("RING")`** — the FOLD /
  DELAYS layout.
- **DELAYS** (`dg_delay_page`): one fixed **MIX** slider; the other five params
  appear one at a time on a **secondary slider** (fixed x=98) while their encoder
  is moved, with the **label + value centred on the bottom row**
  (`dg_sec_caption`), gated on `dc_act_ttl`/`dc_act_kind` so it costs nothing at
  rest.
- GRAINZ **PIT** is a dead control in `wrmz.c` (the taps read at rate 1.0); kept
  parked (it would set the tap read rate / transpose, as the old `grainz.c` did).

### 7.6 Measured / verified
`.run 33,470` (was 33,522), `.bss 85,114`, `imports nothing`, 1193 relocs.
`cftiming` (period 166,686): all-off **98,508**, WRMZ **+7,284**, GRAINZ
**+10,201** — the soft clip added ~120–220 cyc/block over §6's 7,064 / 10,102,
still far under the original 8,521 / 11,399. `late 0`.
`lint` + `patch` byte-verified on 1.43 and 1.44; digiemu boot/settle
(`SETTLED 1450M`, `dsp_running=2`); live diag 0 faults; `tests/_cap_buffx.py`
panel capture confirms the RING and DELAYS layouts.

**Artifacts:** `testout/tonefx-buffx-r2-1.43.syx` / `-1.44.syx` (sha
`7148ac91…`), fw `dn1-0.9f-7148ac91`.
**Files:** `src/buffx.h`, `src/emac.h`, `mods/digiwrmz/wrmz.c`,
`mods/digiwave/wave.c`, `mods/digifold/fold.c`, `mods/digicrush/crush.c`,
`mods/digimeter/meter.c`, `mods/digictl/digictl.c`.

### 7.7 Left on the table
- 4-accumulator MAC interleave on SHFT/GRAINZ (measure-driven; larger rewrite).
- Tune the soft-clip knee (3T/4) on hardware.
- GRAINZ PIT wire-up (parked) and GRAINZ `d`-tap read-rate.
- Hardware pass on the ear-reported items.




---

## 8. Experimental round (ToneFX-BufferFX-exp) — CPU on the heavy modes, quality, pitch

A separate, self-contained sandbox (`ToneFX-BufferFX-exp`, a copy of the 0.9G
tree) so the source repos are untouched. Applied items #1/#2/#7/#9/#11/#12.

### 8.1 #2 (biggest win): specialize the delay loop
`wrmz.c` had `if (mode==0)` **inside** the frame loop, and recomputed the WRMZ
`base`/`span` and GRAINZ `base`/`sp`/`span` (each a `/127` divide) **every frame**.
The loop is now split into two mode-specific loops with those hoisted out (the
mode is block-constant). One branch and two divisions per frame removed.

### 8.2 #1: 2-wide eMAC MAC batch
A 4-wide MAC needs 10 data registers; the 68k has 8, so a 4-wide form is
impossible ("impossible constraints"). `bx_mul15x2` issues two (x*c)>>15 on
ACC0/ACC1 back-to-back; SHFT's four grain-interpolation MACs are two batched
calls. `bx_macsr_frac` now zeroes ACC0-3 so the batch can assume zero.

### 8.3 #12: 24-bit delay line + soft clip
`wz_buf` is now `int` (was `s16`): full 24-bit resolution and feedback headroom,
so 100% wet no longer exposes the line's 16-bit clipping. The old `bx_drive16`
(which clamped to s16) is gone; the write is `bx_soft(f, 0x7fffff)`. Reads use
`bx_read_at` on `int` (bx_mul12, the 24-bit delta × Q12 fraction is a 36-bit
product). GRAINZ `/3` is `bx_mul15(sum,10923)`.

### 8.4 #7 + #12 interact
Halving `WZ_N` (2^15 → 2^14) **and** widening s16 → int32 keeps the line at the
same bytes: `.bss` **85,114 (flat)**, not −32 KB. Net: the line is 24-bit at the
same RAM, max delay 0.68 → 0.34 s. (RAM pool has ~1.18 MB spare, so this is a
non-issue; the max-delay halving is the only cost.)

### 8.5 #11: raised-cosine (Hann) grain window
`wv_win` (triangle, slope discontinuity at the peak) → a **Hann** table, still
satisfying `w[i+128]=32767-w[i]`, so the one-mul complementary crossfade is
unchanged. Smooths the SHFT grain edge (the "distortion" at 100% wet).

### 8.6 #9
The render-load diagnostic (`dg_cpu_guard`/`DG_DTCN0`/...) is already absent from
this tree. The unused `mods/digigrainz`/`mods/digtailz` sources are left (the
`tonefx-buffx-diag` mod.json still references them); PIT stays parked.

### 8.7 Measured / verified
`.run 34,354`, `.bss 85,114`, `imports nothing`. `cftiming` (period 166,685):

| mode | 0.9x (C) | 0.9G (eMAC+clip) | **0.9H (exp)** |
|---|---|---|---|
| all-off | 99,682 | 98,508 | 98,547 |
| WRMZ | +8,521 (0.351) | +7,284 (0.365) | **+3,835 (0.386)** |
| GRAINZ | +11,399 (0.334) | +10,201 (0.348) | **+5,054 (0.379)** |

**−55 % WRMZ, −56 % GRAINZ** vs the pre-eMAC suite. `late 0`. `lint`/`patch`
byte-verified on 1.43 and 1.44; digiemu boot/settle (`SETTLED 1450M`); live diag
0 faults; `_probe_mix` drives WOB/SHFT/FLAN/WIDE with no fault/clip.

**Artifacts:** `testout/exp/tonefx-buffx-exp-0.9H-{1.43,1.44}.elemod`
(`e9857491…` / `00ed5252…`), `testout/exp-1.43.syx` / `-1.44.syx`; fw
`dn1-0.9h-306fe43f`.
**Files:** `src/emac.h`, `src/buffx.h`, `mods/digiwrmz/wrmz.c`,
`mods/digiwave/wave.c`.

### 8.8 Not done / next
- Literal 2× unroll of the WRMZ loop (the specialization above captured the win).
- Hardware ear-pass on the Hann window and the 24-bit line.
- Decide whether to keep WZ_N at 2^14 (0.34 s) or restore 2^15 (0.68 s, +64 KB).

---

## 9. PITCH / STEREO wave CPU (exp, 0.9I → 0.9J)

`tests/_timing_wave.py` (same clock as `_timing_buffx.py`) isolates each wave
mode. The block cost is dominated by the **line memory traffic and eMAC latency**,
not by a hot multiply, so instruction trims give single-digit-% gains:

| mode | worst | **steady (p99 delta)** |
|---|---|---|
| all-off | 98,378 | — |
| WOB | +7,821 | **+2,805** |
| SHFT | +9,984 | **+4,984** |
| FLAN | +9,159 | **+4,115** |
| PAN | +6,446 | **+1,418** |
| WIDE | +5,944 | **+916** |

(The `worst` spikes are the one-time `wv_flush` when a stage switches mode; the
steady-state figure is the p99.)

Applied (safe, no audio change):
- **2-instruction MACs** — the single eMAC helpers no longer do a redundant
  leading `movclr` (ACC0 is already 0 from `bx_macsr_frac`/the previous helper).
  Saves one instruction per multiply across the whole suite (~80–110 cyc/mode).
- **WOB incremental read position** — `rp += 0x10000 − span·2·lstep` per frame
  instead of recomputing `base<<16 + span·l0·2` and the mask (the WOB delay never
  wraps, so no clamp is needed). ~180 cyc.

`.run 34,398`, `.bss 85,114`, `imports nothing`; `lint`/`patch` 1.43+1.44
byte-verified; boot/settle, live diag 0 faults, `_probe_mix` clean.

**Artifacts:** `testout/exp/tonefx-buffx-exp-0.9J-{1.43,1.44}.elemod`
(`99732217…` / `3dad53b7…`), `testout/exp3-1.43.syx` / `-1.44.syx`; fw
`dn1-0.9j-7b3fd534`. **Files:** `src/emac.h`, `mods/digiwave/wave.c`.

### 9.1 Remaining levers (audio trades)
- **s16 (or downsampled) wave lines** — `wv_buf`/`wv_fbuf` are `int` (24-bit);
  halving them halves the line DDR traffic, the dominant cost. Trade: 16-bit
  quantization on WOB/FLAN/SHFT.
- **SHFT nearest-grain** — nearest on the 2nd grain drops 2 loads + 2 MACs/frame
  (SHFT is the heaviest mode). Trade: aliasing on the shifted grain.
- **2× unroll** of WOB/FLAN/SHFT — subsumed so far by the memory bound; small.

---

## 10. eMAC scope hoist + s16 wave lines (exp, 0.9K)

Baseline for this round: **0.9x (pre-eMAC, delay present) idled ~70 %** — so the
70 → 87 % regression came in the eMAC/coeff/24-bit/UI rounds (0.9E → 0.9J), and
§1 suspect #1 is the eMAC. This round applies the plan's §3 (eMAC policy) and §4
(s16 wave lines) and leaves the hardware A/B to the unit.

### 10.1 §3 — one eMAC mode switch per block (scope: `ev_render_out`)

Each handler used to save `MACSR`, select fractional mode and restore it around
its own MACs — up to 6 handlers × (1 read + 1 write + 4 `movclr` + 1 write) per
block. Now **one** `save + set` runs before the chain and **one** `restore` after:

- New subscribers **`digictl_macsr_begin` (order 49)** = `bx_macsr_save()` +
  `bx_macsr_frac()`, and **`digictl_macsr_end` (order 74)** = `bx_macsr_restore()`.
- The modules call **`bx_emac_enter()`/`bx_emac_leave()`** (`src/emac.h`). Built
  with **`-DBX_EMAC_HOISTED=1`** (the suite's `mod.json` cflags, top level **and**
  the 1.44 port) these are no-ops and the block pair owns the switch; a standalone
  module build (no flag) keeps the per-handler discipline, so `mods/digiring`,
  `mods/digiwave`, … still build on their own.

**Scope is deliberately `ev_render_out`, not `ev_render_in`.** From the core
(`mods/core/render.s`) the render handler's *entry* runs the `ev_render_in` list
**before** the whole stock render body, and its *exit* runs `ev_render_out`
**after** it. The stock render "has the EMAC set up for its own use"
(`core-dn1/voice.s`), so the plan's literal "set fractional once in `ev_render_in`"
would leave the stock body running under fractional mode — corrupting it. The
`ev_render_out` list is a tight `jsr` loop with no stock code between handlers, so
it is the correct scope: the DSP is **bit-identical** (same `MACSR` during every
MAC; `ACC0-3` cleared at `begin` and kept 0 by every helper).

### 10.2 §3 alt — `-DBX_NO_EMAC` build knob (the hardware bisect)

`src/emac.h` now forces the scalar C forms even on the ColdFire when
**`-DBX_NO_EMAC=1`** is passed. The C forms are the exact `(x*c)>>k`, so a
no-eMAC build is audio bit-identical; only the mode switch and the MAC latency
disappear. This is the knob for the §1/§3 A/B: if the suite idles near 70 % with
`BX_NO_EMAC`, the eMAC itself (single-mul latency / `MACSR` repack) is the cost,
and the next step is the plan's fallback — keep the eMAC only where it clearly
wins (batched `bx_mul15x2`), `muls.l` elsewhere.

### 10.3 §4 — s16 wave lines + alignment

`wv_buf`/`wv_fbuf` are `short` (were `int`/24-bit), `__attribute__((aligned(16)))`;
the interpolation and the SHFT crossfade run in the s16 scale and convert to the
24-bit bus once (`<< 8`, saturating on write so a >24-bit sum wraps to the rail,
not the sign). Trade (approved): 16-bit quantization on WOB/FLAN/SHFT.

### 10.4 Measured / verified

`cftiming` (`accel=max`, period 166,685):

| | 0.9J | **0.9K** |
|---|---|---|
| all-off | 98,378 | **98,396** |
| WRMZ | +3,835 | **+3,827** |
| GRAINZ | +5,054 | **+5,049** |
| WOB (worst / p99) | +7,821 / +2,805 | **+7,647 / +2,949** |
| SHFT | +9,984 / +4,984 | **+10,115 / +5,280** |
| FLAN | +9,159 / +4,115 | **+9,109 / +4,391** |
| PAN | +6,446 / +1,418 | **+6,138 / +1,407** |
| WIDE | +5,944 / +916 | **+5,736 / +960** |

`.run 33,942` (was 34,398), `.bss 80,014` (was 85,114 — **−5,100 B**, the s16
lines), 1192 relocs, **`imports nothing`**.

> **The instruction model does not see either lever.** It charges cycles, not DDR
> bursts (§4's whole point) and not the eMAC `MACSR`/pipe stall (§3's whole
> point), so the flat-to-marginal numbers above are expected — the hardware meter
> is the judge. At the §1 idle setting (DELAYS off; only RING active) the hoist
> is **neutral** (one handler), so an idle win must come from `BX_NO_EMAC` or the
> UI, not the hoist alone.

Verified: `lint` + `patch` byte-verified on 1.43 **and** 1.44; digiemu boot/settle
(`SETTLED 1450M`, `dsp_running=2`); live diag (WRMZ + GRAINZ, real SSI renders)
**0 faults**; `_probe_mix` 0 clips; `_probe_inject` dry / WRMZ peaks unchanged
(the hoist is bit-exact; WOB/SHFT/FLAN shift slightly, the s16 trade). The
no-hoist (`bx_emac_enter/leave` real) and `BX_NO_EMAC` builds both compile and
link (`imports nothing`).

**Artifacts:** `testout/exp4-1.43.syx` (sha256 `8981fcb8…`) /
`testout/exp4-1.44.syx` (`98a82461…`); fw `dn1-0.9k-8981fcb8`; elemod sha
`082f7812…` (1.43). **Files:** `src/emac.h`, `mods/digictl/digictl.c`,
`mods/digiring/ring.c`, `mods/digieq/eq.c`, `mods/digicrush/crush.c`,
`mods/digifold/fold.c`, `mods/digiwave/wave.c`, `mods/digiwrmz/wrmz.c`,
`mods/tonefx-buffx/mod.json`.

### 10.5 Hardware matrix requested (the only judge)

Same pattern/page, DELAYS off, meter after 60 s; one row per build:

| build | what it isolates |
|---|---|
| 0.9x (pre-eMAC, delay present) | the 70 % reference |
| **0.9K** (hoist + s16, eMAC on) | this round |
| 0.9K with `-DBX_NO_EMAC=1` | the eMAC itself (single muls / `MACSR` stall) |
| 0.9K with `-DBX_EMAC_HOISTED` removed | fold the hoist back out (per-handler scope) |

If **no-eMAC ≈ 70 %**, the eMAC is the regression → apply the §3 fallback. If
**no-eMAC is still ~87 %**, the cost is elsewhere (24-bit delay line DDR, code/
i-cache, or UI) → the §1 bisect continues there.

**Hardware result (user A/B, §3):** the no-eMAC build idles **lower** but is
**worse live** when processing → the eMAC wins overall; **keep the eMAC**. So the
idle regression is not the eMAC single muls, and the remaining idle suspects are
the delay line (live), i-cache, and UI. The meter at idle reflects the **overall
main-CPU load**, so UI redraw is in scope.

---

## 11. Idle suspects: delay line, i-cache, UI redraw (exp, 0.9L)

The three remaining §1 suspects, each as a build knob so each can be A/B'd alone
(plus a combined build), on top of 0.9K:

| knob | change | effect |
|---|---|---|
| **§6 redraw cap** (default on) | `digictl.c`: animated pages redraw at `dc_rate` **3 → 6** (~10 → ~5 Hz), and any page whose section is **OFF** takes the static rate (nothing to animate). Each invalidation redraws the whole stock master page + our overlay, so this halves that work. | fewer UI-task cycles while a page is up |
| **`-DBX_NO_UI_ANIM`** | `digictl_tick` does not periodically invalidate (the page draws once / on input). | isolates the continuous-redraw cost |
| **`-DBX_S16_LINE`** | `wrmz.c` delay line `int`(24-bit) → `short`(s16); interp in the line scale, saturating write. **`.bss` 80,014 → 47,246 (−32,768 B)**; halves the line's DDR traffic. Trade: 16-bit tail quantization. | the §1 "24-bit delay line" bisect (live cost) |
| **`-Os`** (`mods/tonefx-buffx` cflags) | size-optimise the whole mod: **`.run` 34,278 → 26,158 (−8,120 B, −24 %)**, relocs 1198 → 969. | the i-cache / code-footprint bisect |

Combined build = redraw cap (always) + `-DBX_S16_LINE` + `-Os` → `.run 26,094`,
`.bss 47,246`.

### 11.1 Measured

`cftiming` does **not** model i-cache or DDR bursts, so it cannot confirm the
two suspects it is meant to test (it charges cycles only):

| | all-off | WRMZ | GRAINZ |
|---|---|---|---|
| 0.9K | 98,396 | +3,827 | +5,049 |
| 0.9L (`-Os`) | 99,314 | +3,621 | +4,777 |
| 0.9L-comb (`-Os`+s16 line) | 99,321 | +3,481 | +4,892 |

`-Os` helps WRMZ/GRAINZ but its wave `worst` spikes grow (the mode-switch
`wv_flush`) and WOB/FLAN p99 rise a little — expected: less unrolling, and no
i-cache in the model. The **`.run` −24 %** is the signal to test on hardware.

Verified: all variants **`imports nothing`**; `0.9L-os` and `0.9L-comb` patched
byte-verified (1.43) and staged; `0.9L-comb` digiemu boot/settle (`SETTLED
1400M`), live diag **0 faults**, `_probe_mix` **0 clips** (the s16 line is sane).

### 11.2 Hardware matrix requested

| build | isolates |
|---|---|
| 0.9K (baseline) | — |
| **0.9L** (redraw cap only) | §6 UI redraw |
| 0.9L + `-DBX_NO_UI_ANIM` | continuous UI redraw (aggressive) |
| 0.9L + `-DBX_S16_LINE` | the 24-bit delay line (live WRMZ/GRAINZ) |
| 0.9L + `-Os` | i-cache / code footprint |
| **0.9L-comb** (`-Os` + s16 line + cap) | the combination |

**Artifacts (1.43 elemods, in `testout/exp/`):** `tonefx-buffx-exp-0.9L-1.43.elemod`
(`be9cf173…`), `-noanim` (`324b3479…`), `-s16line` (`579dde48…`), `-os`
(`e4b296d1…`), `-comb` (`718b3395…`); syx `exp4L-os-1.43.syx` (`40d423f3…`), `exp4L-comb-1.43.syx`
(`23922945…`). **Files:** `mods/digiwrmz/wrmz.c`, `mods/digictl/digictl.c`,
`mods/tonefx-buffx/mod.json` (flags). 1.44 variants on request.

---

## 12. Wave flush spike (exp, 0.9M)

`_timing_wave.py` shows each mode's `worst` well above its p99 — the one-time
`wv_flush()` when a stage switches mode or re-enables. It cleared **both** lines
(2×(1025+257) = 2564 stores in one block). That was written when FLAN shared the
dry line; since the flanger/pitch split FLAN has its **own** `wv_fbuf`, and
WOB/SHFT **share** `wv_buf`, which each writes the live input into every frame —
so clearing the shared line only puts a read discontinuity in the delay (and
resetting `wv_w` with it makes it incoherent). `-Os` made the flush codegen
worse, so its spike grew.

**Fix:** `wv_flush(mode)` clears only `wv_fbuf` (FLAN's own line), and only when
the returning mode will read it (`mode == WV_FLA`); the shared dry line and
`wv_w` are left alone. `-DBX_FULL_FLUSH` restores the old whole-line clear for an
A/B. (`mods/digiwave/wave.c`.)

### 12.1 Measured (`worst` cycles over all-off; p99 now == worst)

| mode | 0.9K | 0.9L `-Os` | **0.9M** | 0.9M-comb (`-Os`+s16) |
|---|---|---|---|---|
| all-off | 98,396 | 99,314 | 98,361 | 99,300 |
| WOB | +7,821 | +17,025 | **+3,016** | +4,501 |
| SHFT | +9,984 | +18,125 | **+5,491** | +5,534 |
| FLAN | +9,159 | +18,616 | **+5,062** | +6,663 |
| PAN | +6,446 | +13,659 | **+1,372** | +1,392 |
| WIDE | +5,944 | +13,286 | **+1,008** | +916 |

Every mode's margin improves (SHFT worst 0.349 → **0.377**); `late 0`; live diag
**0 faults**. The worst-case spike — what causes late blocks on hardware — is
gone, and it composes with `-Os` and the s16 line. **Artifacts:**
`testout/exp/tonefx-buffx-exp-0.9M-1.43.elemod`, `-os`, `-comb`; syx
`exp4M-1.43.syx`, `exp4M-comb-1.43.syx`. **Files:** `mods/digiwave/wave.c`.

---

## 13. 4.0b / 4.0c round — store, macros, permanent chain, WASH CPU

This round is not a footprint pass: the delay line and the eMAC are unchanged.
It fixes correctness (store/macros), makes the chain order permanent, and trims
the WASH path.

### 13.1 Per-pattern store (digictl 2.9)

The store moved out of the MIDI-track blocks for channels 1-3
(`pattern+0x1040/+0x1410/+0x17E0`, `"DGX1/2/3"`, which a configured MIDI track
writes) into **one reserved MIDI track**: t=7 at `pattern+0x1BB0`, magic
`"DGX4"`, all 51 params packed 1-7 bits each (40 of 64 bytes). Only that track
is touched; channels 1-15 and the synth tracks are untouched. `.bss` stays at
**47,182** (no table); `.run` is ~25.6 K (the packer + guard).
See `docs/PATTERN-STORAGE.md`.

### 13.2 Macros

WASH = WOB only (75 % depth / 30 % rate) + WRMZ mix/fb; RADIO = EQ tilt (0/127)
+ TRSH + SRR. Capture/restore is **per engine** (`MG_*` bits): only the engines
an active macro drives are captured/restored, so CRUSH/REDUX stays live under
WASH. The macro driver runs once per render block; when no macro is on it is a
single flag test.

### 13.3 Permanent chain order

The WAVE insert is split into `digiwave_pitch_render_out` (order 61) and
`digiwave_stereo_render_out` (order 63), with `digiwrmz_render_out` at 62, so the
order is permanently **PITCH → DELAYS → STEREO**. Only the group selected by
`digiwave_page` does work; the other pass is one branch. The DT port does the
same in `master.c`. Code cost: the split adds a wrapper + two entries (~0.2 K).

### 13.4 WASH CPU

While WASH is on the WRMZ now uses `MOD = 0` (static read: no `bx_read_at`
interpolation and no second line read), **skips the DC blocker** (one eMAC MAC
per frame, state reset on enter/leave), and the L/R wet mix uses
`bx_mul15x2` in WOB and WRMZ/GRAINZ (two MACs back to back instead of a serial
`mac → movclr → mac → movclr`). The DC skip is scoped by the per-engine capture
so turning WASH off restores the delay.

Estimated (from the loop structure): the DC skip is ~1 MAC/frame (48/block); the
static read matters only if the base `MOD` was nonzero; the x2 pairing saves a
serial accumulator read per L/R pair. The remaining WASH cost is the delay
line's DDR traffic — the next levers are half-rate wet (~−3.5 k cyc/block),
mono WOB (~−1.5 k), or a delay-time cap (cache); all audible trades.

### 13.5 Current builds (4.0c)

| build | `.run` | `.bss` | sites | relocs |
|---|---|---|---|---|
| Digitone 1.43 / 1.44 | 25,594 | 47,182 | 11 | 970 |
| Digitakt 1.53 / 1.54 | 23,096 | 51,232 | 4 | 931 |

`imports nothing`; lint links; patch byte-exact. The measured `cftiming` numbers
above (§12) are from the 0.9x line; a fresh timing pass on 4.0c is the first task
of the next round.
