# ToneFX-BufferFX — implementation plan (WRMZ / Grainz / Tailz / Cloudz / Loopz)

Status: **plan only** (no code). Sandbox: `C:\Users\benan\Music\ELEKTRON\ToneFX-BufferFX`.
**Tone+FX is a read-only reference** (`digitone_corea`); this plan and the new FX
live entirely inside this sandbox.

Builds on **core-dn1 4.0** and the Digitone profile's **`bulk`** free DDR area.
Companion to `digitone_corea\docs\FX-PLAN.md` (the digicrush/digiwave plan) and to
`TONEFX-IRPINA\digicosm-tonefx\docs\DIGICOSM-RECREATION.md` (the GRAIN/VERB
recreation that had to stop at a 0.17 s delay because it stayed inside 128 KB).

---

## 0. The idea

Tone+FX proves the master-insert pattern; its delay engine (`digiwave`) is
deliberately tiny (1024 frames ≈ 21 ms). This sandbox keeps that architecture and
adds a family of effects whose whole point is **long buffers**:

- **WRMZ** — a modulated delay with a real, musical time (tape/BBD/ensemble).
- **Grainz** — a **granular delay**: windowed grains over a history, fed back.
- **Tailz** — **Space**: a full algorithmic reverb (FDN) with long tails, freeze.
- **Cloudz** *(stretch)* — shimmer: grains → pitch → reverb tail.
- **Loopz** *(stretch)* — a looper: record / overdub / undo / reverse / hold.

The long buffers need memory the suite never had. Three facts make that possible
(all recorded in this workspace):

1. **core-dn1 4.0 gives the mods 1.25 MB** at `0x43EC0000–0x44000000` for
   `.run` + `.bss` (was 128 KB). `elekloader\devices\digitone_mk1.py` (`core_ddr`).
2. **The profile exposes `bulk` `0x44000000–0x47BE0000` (~60 MB)** that a mod
   claims as `resources.regions` and uses at run time; the OS never clears it.
3. **It already ships:** `mods/digicosm-dn1` claims `0x44000000–0x45B00000`
   (26 MB of looper + history + delay + 8-line FDN), `mods/digichroma-dn1`
   claims `0x45B00000–0x46200000`. Both are working references for the exact
   mechanism used here.

The trade: a claimed region means the build is no longer a drop-in `tonefx` for
users who also run region-claiming mods. That is why this is its own sandbox.

---

## 0b. Placement — append-only, at the end of the chain

**The new FX do not replace or alter any existing Tone+FX effect.** They are
**appended after** the whole existing master chain, so they hear the sound the
suite has already made: ring-modulated, EQ'd, crushed, folded and flanged.

```
existing suite (unchanged, in place):
   ring 50 → EQ 55 → crush 57 → fold 60 → wave 62
then, appended:
   WRMZ → Grainz → Cloudz → Tailz → Loopz
then, still last:
   ceiling → meter
```

Consequences that drive the design:

- **The buffers see processed audio.** Delaying/reverbing a flanged, folded,
  ring-modulated signal is the point — tails carry the character of the front
  stages. No routing option is needed for this; it is simply the chain order.
- **The front stages stay byte-for-byte as shipped.** The existing orders
  (50/55/57/60/62) are not touched and the modules are not edited; the new
  inserts only add orders *after* 62. `digictl_limit_out` (the output ceiling)
  and `digimeter` move to the end, after the new stages, so nothing added can
  clip and the meter measures the finished result.
- **This is the opposite of a "pre-FX routing" option** (the suite's parked
  wish-list item). It is serial and additive: the suite's sound → the buffer FX.
- **No feedback runaway into the front stages:** the new stages only feed their
  own buffers; the master ceiling remains the last stage.

> If a user wants a *clean* delay/reverb of the dry signal instead, they bypass
> the front pages (each true-bypasses) — the chain order itself is not changed.

---

## 1. Scope

| product | module id | what | buffers | tier |
|---|---|---|---|---|
| **WRMZ** | `digiwrmz` | modulated delay: TIME, FB, TONE, MOD DEPTH/RATE, MIX; modes TAPE / BBD / ENSEMBLE / CHORUS | 2 stereo lines (short + long) | **core** |
| **Tailz** | `digitailz` | Space reverb: 8–16 line FDN, PRE, DIFF, MOD, TONE, DECAY, SIZE, MIX, **FREEZE** | many short lines | **core** |
| **Grainz** | `digigrainz` | granular delay: head pool over a history, windowed grains summed and **fed back** | history (10–20 s) + feedback line | **core** |
| **Cloudz** | `digicloudz` | shimmer/cloud: grains → pitch → reverb tail (Grainz + Tailz + SHIFT) | history + FDN (shares) | stretch |
| **Loopz** | `digiloopz` | looper: REC / PLAY / DUB / UNDO / REV / HOLD / SPEED / LEVEL | 60 s stereo ×2 layers | stretch |

Every module is an ordinary Core A master insert (the `digicrush`/`digiwave`
pattern) whose big buffers additionally live in a claimed `bulk` region, and is
**appended at the end of the chain (§0b)** — after ring/EQ/crush/fold/wave — so
it delays and reverberates the suite's already-processed sound. The existing
suite is **unchanged in behaviour**.

**Two tiers, so the compatibility trade is explicit:**

- **Tier 0 — `.bss` under core 4.0 (no region).** The 1.25 MB `.run`+`.bss` pool
  already fits **WRMZ** (2 s stereo), a reduced **Tailz** (8 × 0.15 s) and a
  short **Grainz** history with **no region claim and no compatibility change.**
  Land this first.
- **Tier 1 — claimed `bulk` region.** Multi-second (up to 60 s) stereo lines, a
  large FDN, a long grain history and the looper. Needs core-dn1 3.2+ (use 4.0)
  and a region disjoint from other region mods.

---

## 2. Memory model

### 2.1 Tier 0 — the core-dn1 4.0 `.bss`

The linker lays `.run` then `.bss` from `0x43EC0000` to `0x44000000` (1.25 MB);
the core's boot copier **zeroes `.bss`**, so Tier-0 buffers need no runtime
clear. The suite is `.run 28889, .bss 19454` — nearly the whole pool is free.
Keep total all-mods `.run`+`.bss` well under 1.25 MB (the patcher refuses a blob
the bootloader could not unpack in place).

### 2.2 Tier 1 — the `bulk` region

```
bulk area        0x44000000 – 0x47BE0000   59.75 MB   (device profile)
  DigiCosm       0x44000000 – 0x45B00000   27.0  MB   (released)
  DigiChroma     0x45B00000 – 0x46200000    6.5  MB   (released)
  free           0x46200000 – 0x47BE0000   25.9  MB   <- this sandbox's budget
```

**Proposed region: `0x46200000 – 0x47BE0000` (25.9 MB)**, declared in
`mods/tonefx-buffx/mod.json`:

```json
"resources": {
  "core": "4.0",
  "regions": [{"name": "tonefx-buffx buffers", "lo": "0x46200000", "hi": "0x47BE0000"}]
}
```

Linker rules (`elekloader/elemod.py:parse_resources`, `link.py:check`): every
region must lie inside **one** free area; **no two regions may overlap** — so a
user installing Tone+FX *and* DigiCosm is fine only because the ranges are
disjoint. A future bulk mod must not claim inside this slice. Shrink the claim to
just what ships to lower that risk.

### 2.3 Addressing and clearing (both tiers)

- **Regions emit no symbols.** Hardcode the base (`#define BX_BULK 0x46200000u`)
  and lay buffers at **fixed offsets**, like `digicosm-dn1/dcosm.h`
  (`DC_HIST`, `DC_DLY`, `DC_REV`, `DC_LOOPA/B`). Deterministic and map-checkable.
- **The OS never clears `bulk`.** Clear every buffer **before first read**, in
  the **UI task** (`ev_tick`), never the render — a multi-MB `memset` at
  interrupt level misses the block deadline. Pattern (DigiCosm): a small state
  machine clears N KB per tick, then arms a `*_ready` flag; each render
  early-outs to passthrough until `*_ready`, and the page shows `WAIT`.
- **Power-of-two ring sizes** wherever a read is masked (`& (N-1)`), never mod.

---

## 3. Design envelope (unchanged from the suite)

- **Core A**, `ev_render_in`/`ev_render_out` master inserts, subscription-only.
  `ev_render_in` stores `dn_out_off()`; `ev_render_out` processes
  `0x80001A00 + off` (256 B, 32 stereo frames) in place.
- **48 kHz, 32-frame stereo blocks, int32 24-bit left-justified**; work in `s16`
  internally (`>> 8` / `<< 8`), as the GRAIN/VERB recreation does.
- **1500 blocks/s, 166,667 core cycles/block.** Stock render ≈ 56.6 %; the suite
  adds on top. Measured references (recreation, old 128 KB build): a 4-line FDN
  reverb ≈ 12 k cyc/block worst; a 16 KB / 4-tap cloud ≈ 7 k; both on left 28 %
  of the period spare, **0 late renders**.
- **ABI:** handlers `void f(void)`, interrupt level. `d1/a0/a1` free; **leave
  `MACSR` as found** if the EMAC is used.
- **No libc, no FPU, `imports nothing`.**
- **Block-rate parameters + per-frame ramp; ramped true bypass** that returns
  before the per-sample loop when settled (the suite's rule).

---

## 4. Shared primitives — `src/buffx.h`

One header of integer primitives, so WRMZ / Grainz / Tailz / Cloudz / Loopz all
share engines instead of five copies (the suite's "one engine" ethos). Reuse
`dn_mul15` / `dn_mul14` / `dn_out_off` from `corea.h` and `sin256` from
`sin256.h`.

| primitive | from | use |
|---|---|---|
| `bx_rd(line, mask, pos20_12, &l, &r)` | `digiwave` `wv_read` | fractional interpolated stereo read, clamped |
| `bx_wr(line, mask, &w, l, r)` | `digiwave` | ring write, mask wrap |
| `bx_lfo(phase, rate)` | `digiwave` `wv_sin` | block-rate sine + linear per-frame ramp |
| `bx_lp(s, x, c)` / `bx_hp` / `bx_dc` | `digieq`, `digiwave` | one-pole damping, DC blocker in feedback loops |
| `bx_ap(buf, len, &w, x, g)` | DigiCosm `space_render` diffusion | allpass diffuser |
| `bx_svf(&s, x, f, q)` (Q14) | DigiCosm `filter_render` | per-head / tone resonant filter |
| `bx_sat(x)` | `digifold` | stateless saturator (tape drive, feedback safety) |
| `bx_win[256]` (Q15) | DigiCosm `dc_win` | Hann grain window |
| `bx_head` pool | DigiCosm `heads_render` | grain heads: one-shot + loop, windowed, panned, per-head filter/crush |
| `bx_clear_step()` | DigiCosm `dcosm_clear_step` | incremental region clear + `*_ready` arm |

`bx_head` is the Grainz/Cloudz core: position 20.12 frames, `inc` 20.12/frame,
`prog` step per block, nearest or interpolated reads, optional per-head SVF.
Tables (`bx_win`, ratio tables) are `const` in `.run`, built at compile time.

---

## 5. The named inserts

### 5.1 WRMZ — modulated delay (`digiwrmz`, page kind 11)

A warm, modulated delay: the musical middle ground between `digiwave`'s FLAN
(≈21 ms) and a static echo.

- **Modes** (H knob / a trig): **TAPE** (slow wow + fast flutter, saturation,
  dark repeats), **BBD** (short, dark, clock-noise character), **ENSEMBLE**
  (three modulated taps at different LFO phases, panned L/C/R, wide), **CHORUS**
  (short modulated delay, no feedback).
- **Controls (0–127):** A on/off · B TIME (free; FUNC snap) · C FB · D TONE ·
  E MOD DEPTH · F MOD RATE · G MIX · H MODE.
- **DSP:** per-sample `pos = w - (time + depth·lfo)` through `bx_rd`; LFO at
  block rate with a per-frame ramp; TAPE adds a second slow LFO (wow) plus
  `bx_sat`; feedback through `bx_lp` (TONE) + `bx_dc`, capped ≤0.95. ENSEMBLE =
  three `bx_rd` taps summed panned.
- **Buffers:** Tier 0 `2 × 96000 s16` = 375 KB (2 s/ch); Tier 1 `2 × 480000` =
  1.875 MB (10 s/ch). CHORUS/ENSEMBLE need < 100 ms — same line, short read.
- **Cost:** ~40–70 cyc/frame/channel.

### 5.2 Tailz — Space reverb (`digitailz`, page kind 13)

A proper room, past the recreation's 4-line 16 KB FDN. Directly generalises
DigiCosm's `space_render` (8 lines) and the recreation's `digiverb.c` (4 lines).

- **Controls:** A on/off · B SIZE (scales all line lengths) · C DECAY · D TONE
  (damping) · E PRE (pre-delay) · F MOD (line modulation) · G DIFF (diffusion) ·
  H MIX; **FREEZE** momentary on a trig (feedback 1.0, input muted).
- **DSP:** 8–16 mutually-prime FDN lines (e.g. primes around 1499–3011, scaled by
  a Q8 room multiplier — `rv_base`/`rv_mult` from `space_render`); a
  Householder (or Hadamard) feedback mix; per-line `bx_lp` damping; modulated
  read positions (`bx_lfo`) to break metallic ringing; four input diffusion
  allpasses (`bx_ap`); a pre-delay line; stereo output from alternating lines
  (`yl = Σ even`, `yr = Σ odd`).
- **Buffers:** Tier 1 16 lines × up to 0.8 s ≈ 2.5 MB + pre 0.2 s 0.4 MB +
  allpasses; Tier 0 8 × 0.15 s ≈ 0.5 MB.
- **Cost:** heaviest — an 8-line FDN ≈ 20–30 k cyc/block, 16-line ≈ 40–60 k.
  Carries the auto-bypass guard; measure the full chain.

### 5.3 Grainz — granular delay (`digigrainz`, page kind 12)

Not a plain cloud: a **granular delay** — the grains' output is fed back into the
history, so it smears, pitches and spirals over time.

- **Controls:** A on/off · B DENS (grain rate; CCW sparse → CW dense/random) ·
  C SIZE (grain length 20–500 ms) · D PITCH (grain rate ±12 st / interval) ·
  E SPRAY (position jitter) · F FB (feedback into the history) · G MIX ·
  H DIR (fwd / rev / alternate).
- **DSP:** the `bx_head` pool (DigiCosm `heads_render`): one-shot and loop
  grains, Hann-windowed (`bx_win`), 20.12 positions, interpolated, panned;
  optional per-head `bx_svf`. Sum heads into the wet bus; feed the wet (scaled
  by FB) back into the history's write input through a short delay line — the
  "delay" part. **Head cap + CPU guard**: cost scales with live heads.
- **Buffers:** history stereo s16 10 s = 1.875 MB (Tier 1; 20 s = 3.75 MB);
  feedback line 2 s = 0.375 MB. Tier 0: a short (2 s) history.
- **Cost:** scales with heads — keep a head cap (DigiCosm: ≤16, reduced above
  ~45 % of a block).

### 5.4 Cloudz — shimmer / cloud (`digicloudz`, page kind 14) *(stretch)*

Grainz (dense grains) → a pitch stage (+12 st or ±interval, reuse `digiwave`
SHFT-style two-grain crossfade) → a Tailz-style reverb tail, with the
pitch-shifted tail fed back — the classic shimmer. Shares Grainz's history and
Tailz's FDN (same region, same code, different routing).

- **Controls:** DENS · SIZE · PITCH (shimmer interval) · SPRAY · TONE · MIX,
  plus ROOM/DECAY.

### 5.5 Loopz — looper (`digiloopz`, page kind 15) *(stretch)*

Straight from DigiCosm's looper: a 60 s stereo record buffer + one overdub layer
for undo, with REC / PLAY / DUB / UNDO / REV / HOLD / SPEED / LEVEL / FADE and
optional tempo-quantized close. Commands taken at the next block; the overdub
layer is cleared incrementally by the UI tick (`dcosm.lclear_len`).

- **Buffers:** `2 × 60 s × 2 ch × 2 B` = 23 MB — the reason `bulk` exists.
- On the **master bus** (post-FX loop) by default.

---

## 6. Signal order

Current `ev_render_out`: `ring 50 → EQ 55 → crush 57 → fold 60 → wave 62 →
ceiling 64 → meter 65`.

**Append-only** (see §0b): the existing orders 50/55/57/60/62 are untouched; the
buffer family is inserted strictly *after* `wave 62`, and the suite's two tail
stages move to the very end:

```
ring 50 → EQ 55 → crush 57 → fold 60 → wave 62 →
   WRMZ 63 → Grainz 64 → Cloudz 65 → Tailz 66 → Loopz 68 →
   ceiling 70 → meter 71
```

`digictl_limit_out` moves from 64 to 70 and `digimeter` from 65 to 71; both now
run on the post-buffer result, so a hot delay/reverb tail is still limited and
the meter shows the finished master. (Order values need not be contiguous.)

> Confirm at build time that moving `digictl_limit_out` / `digimeter` is
> inaudible except for the intended "buffer FX before the ceiling" behaviour (the
> ceiling only clamps; the meter only reads). This is the deliberate end-of-chain
> placement, not a stock change.

---

## 7. Pages, store, CC, PERFORM

Register new **kinds 11–15** in every list `digictl` enumerates (`dc_kinds`,
`dg_page_off`, the `add_page` bound, the enc/trig gates). Draw in the `digictl`
style (direct framebuffer, OFF/MACRO cue, redraw gating ~10 Hz animated / ~4 Hz
static).

- **Pages:** `11 WRMZ · 12 Grainz · 13 Tailz · 14 Cloudz · 15 Loopz`.
- **Store:** block 1 (`DGX1` v10, 64/64) and block 2 (`DGX2` v2) are full. Use
  the spare MIDI-track blocks (`DGX3` at `pattern+0x17E0`, `DGX4` at
  `pattern+0x1BB0`) **or, cleaner, core 4.0's `core_projdata`** (`projdata:<TAG>`
  — DigiCosm/DigiChroma use it), which retires the configured-MIDI-track risk.
- **MIDI CC:** free numbers via the existing `digictl_cc_apply` switch; verify
  against the stock CC table `0x4018D104`.
- **PERFORM:** extend the `pf_*` momentary-pad blocks (one depth per insert);
  FREEZE and Grainz DENS are natural pads.

---

## 8. Memory budget

| item | where | footprint |
|---|---|---|
| WRMZ lines (10 s stereo s16) | `bulk` | 1.875 MB |
| Tailz FDN (16 × 0.8 s) + pre + allpass | `bulk` | ~3.0 MB |
| Grainz history (20 s stereo) + fb line | `bulk` | ~4.1 MB |
| Loopz (60 s stereo ×2) | `bulk` | 23.0 MB |
| Cloudz | shares WRMZ/Grainz/Tailz | 0 |
| all state, tables, pages | core 4.0 `.bss`/`.run` | < 120 KB |
| **Tier-0 only** (WRMZ 2 s + Tailz 8-line + short Grainz) | `.bss` | ~1.0 MB of 1.25 MB |

Tier 0 just fits the 1.25 MB pool; Tier 1's buffers are all in `bulk`, code and
state stay tiny. Ship a region sized to the modules that actually land.

---

## 9. CPU, headroom, guards

- This rides on a master render already ~57 % busy, and the family stacks. Guards
  (from the DigiCosm recreation):
  - **Head cap + CPU guard** for Grainz/Cloudz (and the looper's reads): fewer
    new grains above ~45 % of a block, more allowed below ~30 %, timed on `DTCN0`
    (`0xFC07000C`).
  - **Sustained-overload auto-bypass:** over ~94 % of a block for ~0.25 s → turn
    that section off, set `*_overload`, show `CPU` on the page; re-arm on a knob
    move. This is what makes a hot reverb/looper setting never hang the unit.
  - **True bypass off** (zero per-sample cost); lines silent but tails faded.
- Guidance for users: not all five at once; each true-bypasses.
- Measure with `emu.portable --check --timing` on the default chain, then the
  heaviest (WRMZ + Grainz + Tailz on). Target: no late renders, ≥20 % spare.

---

## 10. Implementation order

0. **Tier-0 WRMZ** in `.bss` (core 4.0). No region, no compat change. Proves the
   long-line idiom, sync, page, store.
1. **Tier-0 Tailz** (8 lines) in `.bss`. Confirms a full FDN fits and its cost.
2. **Claim the region**, move the buffers, add the incremental clear + `*_ready`
   gating. Build/lint/patch as a normal `tonefx-buffx`.
3. **Grow**: WRMZ to 10 s stereo, Tailz to 16 lines + modulation, Grainz history.
4. **Cloudz**, then **Loopz** as stretch.
5. Store (`DGX3+` or `core_projdata`), CC, PERFORM pads, docs, polish.

---

## 11. Testing

- **Build/lint/patch:** `.run`/`.bss` sizes; `imports nothing`; every site
  byte-checked; the region listed (`link.regions`) and disjoint from
  DigiCosm/DigiChroma. Build both OS 1.43 and 1.44 (`ports`).
- **Emulator (digiemu, patched-Unicorn venv):** boot/settle `dsp_running=2`;
  `kinds=[16,15,17,0..15]`; each page renders and toggles; live, each insert runs
  with **0 faults**. Reuse `digitone_corea\tests\_diag_perf.py`, `_diag_macros.py`,
  `digiemu_pattern_store.py`, `digiemu_midi_cc.py`, and the recreation's
  `digiemu_grain.py` / `_live.py`.
- **Region clearing:** assert buffers read zero before first write; assert the
  `*_ready` gate makes the render passthrough until armed.
- **CPU:** bounded `cftiming` (`accel=max`) all-off / each-on / all-on, then the
  full `emu.portable --check --timing`.
- **Hardware:** boot, long busy patterns with each insert, tails, bypass
  exactness, freeze stability, and the auto-bypass guard. **No ship without a
  hardware pass.**

---

## 12. Risks / open questions

- **Compatibility is the headline trade.** A claimed region makes the build fail
  beside an overlapping region mod. Keep a **no-region Tier-0 build** for users
  who run DigiCosm/DigiChroma; document the region partition.
- **Region collision:** `0x46200000–0x47BE0000` clears both released region mods;
  keep the claim narrow and coordinate a future partition.
- **Core minimum:** regions need 3.2, the 1.25 MB `.bss` needs 4.0 — declare
  `"core": "4.0"`.
- **CPU:** Tailz (16-line) and Grainz (heads) are the heavy ones; the honest test
  is hardware, not the emulator.
- **Freeze/DECAY=1.0 stability:** clamp feedback and use `bx_sat` / a DC blocker
  so infinite-tail settings cannot run away.
- **Shimmer design (Cloudz):** pitch-in-loop needs a clean shifter; `digiwave`
  SHFT is deliberately lo-fi — decide accept-lo-fi vs a better grain shifter.
- **Store clash:** prefer `core_projdata` over more MIDI-track blocks.
- **`.bss` ceiling:** Tier-0 buffers share the 1.25 MB with every mod; leave
  margin.

---

## 13. References (all outside this sandbox, read-only)

- `digitone_corea\mods\digiwave\wave.c` — delay idioms (`wv_read`, `wv_sin`).
- `digitone_corea\mods\digicrush\crush.c`, `mods\digifold\fold.c`,
  `mods\digieq\eq.c`, `mods\digimeter\meter.c` — insert + filter/saturator patterns.
- `digitone_corea\mods\digictl\digictl.c`, `mods\tonefx\mod.json` — pages,
  store, CC, PERFORM, subscription orders, sites, ports.
- `digitone_corea\src\corea.h`, `src\sin256.h` — fixed-point helpers + sine table.
- `digitone_corea\docs\FX-PLAN.md`, `docs\OPTIMIZATION.md`,
  `docs\PATTERN-STORAGE.md`, `docs\MIDI-CC.md`, `DSP.md`.
- `00 ELEKLOADER NEW\elekloader-main\mods\digicosm-dn1\` (`mod.json`, `dcosm.h`,
  `dsp.c`) — the working `bulk`-region reference: history, delay taps,
  **8-line FDN Space** (`space_render`), looper, **grain heads** (`heads_render`).
- `TONEFX-IRPINA\digicosm-main\dsp.c` — the same DSP, readable.
- `00 ELEKLOADER NEW\elekloader-main\mods\digichroma-dn1\mod.json` — the second
  region claimant.
- `TONEFX-IRPINA\digicosm-tonefx\mods\digigrain\`, `...\mods\digiverb\` — the
  128 KB GRAIN/VERB recreation; `...\docs\OPTIMIZATION.md` §11 — measured CPU.
- `digigrain-main\mods\digigrain\src\grain.c` — grain spawn/window/playback.
- `00 ELEKLOADER NEW\elekloader-main\elekloader\sdk\include\digitone-mk1\core3.h`
  — `resources.regions`, `core_audio`, `fw_tempo`, `core_projdata`.

> Not affiliated with, endorsed by or supported by Elektron. Flashing modified
> firmware is at your own risk; no firmware is included or distributed.
