# Tone+FX — performance-optimization plan

Branch `perf-opt` (experimental worktree), forked from `tonefx 3.5d`. Goal:
**lower CPU and memory footprint without changing what the suite does** (except
where an item explicitly trades audio quality). Companion:
`docs/PERF-OPT-INSTRUCTIONS.md` (how to execute + measure). Ledger to keep
updated: `docs/OPTIMIZATION.md`.

## Summary

| # | item | impact | effort | risk | audio | status |
|---|---|---|---|---|---|---|
| 1 | Direct framebuffer UI drawing | **high** | M | low | none | **landed** |
| 2 | Fuse the master passes | **very high** | L | med | none | pending |
| 3 | Partial screen clear | med | S | low | none | pending |
| 4 | Meter gated on visibility | med | S | low | none | **landed** |
| 5 | Ceiling gated on "hot" | low–med | S | low | none | **landed** |
| 6 | Cache `dn_out_off()` | low | S | low | none | **rejected** |
| 7 | EMAC for the multiplies | **high** | L | med | none | pending |
| 8 | Ring LFO → block-rate | med | S | low | none | pending |
| 9 | SHFT trim (2nd grain) | med | M | med | tiny | pending |
| 10 | Cheap `dn_q15` blend option | med | S | low | lo-fi modes only | pending |
| 11 | Hoist per-sample branches | low | S | low | none | **landed** |
| 12 | Delay line: downsample / 12-bit / shorter | **high** | M | med | yes (trade) | pending |
| 13 | Hot tables to `.fast` SRAM | high | L | high | none | pending |
| 14 | Store-sync gating | low | S | low | none | **landed** |
| 15 | Compiler flags / unroll / alignment | med | S | low | none | **rejected** |

Landed-item numbers live in `docs/OPTIMIZATION.md` §9 (perf-opt ledger).

`S/M/L` = small/medium/large. Start with **1, 3, 4, 8, 10** (cheap, safe); then
**2** and **7** (structural); **12** alongside the flanger work.

---

## 1. Direct framebuffer UI drawing

**Where:** every `dg_*_page` in `mods/digictl/digictl.c` (and any future page).
Today each pixel is a `DN_FILLRECT` **function call** (`0x400DD292`), so a page
costs dozens–hundreds of calls/frame.

**How:** the panel is 1 bpp; `byte = page + 8*column`, `page = 7-(y>>3)`,
`bit = y&7`, at the front buffer (`fb_front`; `mods/tonefx/render.c` already
pokes `FBP = 0x40241a44` directly). Add a tiny local `px(x,y)` / `span(x,y0,y1)`
that ORs bytes in the fb, and draw the graphics with it. Keep `DN_TEXTF` for
text (or use the same fb for glyphs). This removes the call overhead entirely.

**Impact:** the biggest UI win; no visual change. **Verify:** screenshot each
page (digiemu `panel.Capture`) before/after; count calls.

**Status: landed** on `perf-opt`. New helpers `dg_px`/`dg_fill` write the panel
bytes at `fb_front` (the same buffer the stock draw uses) in the stock
coordinate frame; `dg_glyph`, the dot/span/clear routines and every page graphic
were converted. `DN_TEXTF` was kept for the strings and the single slider frame
kept `DN_FRAMERECT` (exact corner parity). 36 `DN_FILLRECT` sites → 0; FOLD /
PITCH / macro pages went from dozens of calls per frame to none. `.run`
26863 → 26707, `.bss` 25562 → 25566, relocs 917 → 908, `imports nothing`;
RING/FOLD/TILT screenshots byte-identical (digiemu `dn1-35p1-f001f93a`).

## 2. Fuse the master passes

**Where:** the six `ev_render_out` handlers (`ring.c` 50, `eq.c` 55, `crush.c`
57, `fold.c` 60, `wave.c` 62, `meter.c` 65) plus `digictl_limit_out` (64) each
loop the 32 frames → each frame is loaded/stored ~7×.

**How:** one fused `tonefx_master()` that loads `{L,R}` once, runs ring → EQ →
crush → fold → wave → ceiling → meter inline, stores once. Keep each module's
code as inline helpers; subscribe one handler instead of seven. Preserve the
exact order and each section's true bypass.

**Impact:** order-of-magnitude fewer loads/stores — the single biggest render
win. **Risk:** refactor; keep bit-identical output on the factory pattern
(A/B the buffer in digiemu). **Verify:** `emu.cftiming` before/after + A/B audio.

## 3. Partial screen clear

Every page clears the whole drawable area (`FILLRECT(0,0,127,52,0)`) then
redraws. Clear only the region a page animates (a band), or skip the clear on
static pages. **Where:** the `dg_*_page` prologues. **Impact:** med; pairs with
#1.

## 4. Meter gated on visibility

**Where:** `mods/digimeter/meter.c` `digimeter_render_out` scans every block
(~15 insn/frame) but the bars are only drawn on the FOLD page. Gate it: only run
when `dc_vis>0` **and** `cur_kind == DN_FEKIND` (expose a flag from `digictl`),
or fold the peak scan into #2. **Impact:** ~15/frame when not on FOLD.

**Status: landed.** `digictl_meter_active()` (extern, read via a weak ref so a
standalone meter build still links) is true only while the FOLD page is up;
`meter.c` returns early otherwise. cftiming A/B on the default page: render
worst 99965 → 99557 cyc, p99 99958 → 99550, margin 40.03% → 40.27%. FOLD page
unchanged (screenshot identical).

## 5. Ceiling gated on "hot"

**Where:** `digictl_limit_out` (order 64) runs every block. Track an "any hot
setting" flag (flanger feedback > 0, SHFT active, fold/crush drive > 0) and skip
the limiter when nothing can overshoot — or fold it into #2. **Impact:** small.

**Status: landed.** `dn_fx_hot()` (conservative: ring depth, EQ non-flat,
fold/crush amount, any WAVE mode, any macro) gates the limiter. All clean:
cftiming render worst 96086 → 95140 cyc, p99 96086 → 95140, margin 42.35% →
42.92%. When hot the limiter runs as before (default FX: margin 0.4027 →
0.4026, the ~15-cycle check). Pages identical. Note this bends the original
low–med rating — the win is ~950 cyc whenever the mix is clean.

## 6. Cache `dn_out_off()`

`dn_out_off()` (reads eDMA SADDR) is called in **7** handlers per block. Compute
it once in `digictl_mod_in` (order 40, runs first) into a shared `volatile`, and
have the others read it. **Impact:** small; trivial.

**Status: rejected (measured regression).** `dn_out_off()` is already a
`static inline` (a single uncached register read), not a call, so a shared
cache only adds work. Implemented via a COMMON symbol set in `digictl_mod_in`:
`.run 26791 → 26907` (+116), relocs 915 → 929, and `cftiming` render worst
99557 → **99575** cyc, mean 99140.8 → **99154.4** — the extra cached load and
branch per handler cost more than the six eDMA reads saved (cftiming gives no
credit for the uncached read). Reverted; the premise (that it is a call) was
wrong.

## 7. EMAC for the multiplies

**Where:** `dn_mul15` / `dn_mul14` (`src/corea.h`) are 2 muls + shifts; used in
ring, EQ, fold, wave. The MCF5441x **EMAC** does an exact 32×32→64 MAC in one
op; the core saves/restores EMAC around handlers. **How:** add EMAC-based
helpers (set up MACSR once per block in `ev_render_in`, restore after), or a
`dn_mac` that uses the accumulator. **Caveat:** leave `MACSR` as found; verify
the product scaling (signed fractional). **Impact:** high for the multiply-heavy
modes. **Verify:** A/B bit-exactness.

## 8. Ring LFO → block-rate

**Where:** `mods/digiring/ring.c` interpolates `sin256` **per sample**. Switch
to one sine per block + a linear per-sample step, exactly like `digiwave`'s LFO
(`wv_sin` + `lstep`). **Impact:** ~28→~20 insn/frame. **Verify:** same carrier
shape (A/B).

**Review note (perf-opt): needs care — not a plain drop-in.** `digiwave`'s LFO
tops out at ~12 Hz, so one sine per block (32 samples = 21 ms) is ~0.25 of a
cycle and the linear step is exact enough. **`digiring`'s carrier is audio-rate**:
`ft = 1 + freq*15` is 1..1906 Hz, up to **~1.3 carrier cycles per block**, so a
single block-rate sine + linear step would alias the carrier badly. A safe form
would have to keep per-sample phase and only block-rate the *value*, and/or
switch to the block-rate path only below a low-frequency threshold. Treat #8 as
a quality/CPU trade to be measured, not the "audio: none" the summary says.

## 9. SHFT trim

**Where:** `wave.c` SHFT does 8 loads + 4 interp muls/sample. Options: nearest
on the **second** grain (keep interp on the first), or a single-grain mode. The
crossfade is already one mul/channel. **Impact:** med (SHFT is the heaviest
mode). **Trade:** slightly more aliasing in the shifted grain.

## 10. Cheap blend option

**Where:** WOB/FLAN wet blends use exact `dn_mul15`. A `dn_q15` (1 mul) variant
is ~-36 dB noisier but cheaper. Add a per-mode/`const` switch or a build flag.
**Impact:** med on the delay modes. **Trade:** noise on lo-fi material only.

## 11. Hoist per-sample branches

**Where:** e.g. `crush.c` BITS dither `if (dith)` inside the loop. Split into two
loop variants (dither on/off) selected once per block. Sweep all modules for
per-sample conditionals on block-constant values. **Impact:** small.

**Status: landed.** The only block-constant per-sample branches were `crush`
BITS `if (dith)` and `fold` `if (dg)`; `wave`'s per-sample tests are all
data-dependent (clamps, grain wrap, pan sign) and could not be hoisted. Both
split; cftiming with the FX forced on: render worst 104579 → 104158 cyc, p99
104565 → 104158, margin 37.26% → 37.51%. Bit-identical (same ops).

## 12. Delay line footprint (downsample / 12-bit / shorter)

**Where:** `wave.c` `wv_buf[2][2049]` (16 KB) in **DDR** — the largest
allocation, and DDR accesses cost more than the instruction count implies.
Options (trade quality):
- **Downsample:** write the line every 2nd sample; reads interpolate. Halves
  writes/DDR traffic. Slight HF loss on WOB/FLAN/SHFT.
- **12-bit:** store as `int16` capped to 12 bits → ~8 KB, halves traffic; big
  quantization on the 24-bit bus (lo-fi modes).
- **Shorter:** `WV_N` 2048→1024 (~21 ms) frees 8 KB; plenty for WOB/FLAN/SHFT.
Pair with the flanger flush/prime (HANDOFF §6) so quality stays clean.
**Impact:** high on the delay modes. **Verify:** A/B + a `cftiming` pass.

## 13. Hot tables / code to `.fast` SRAM

**Blocked today:** the DN device profile claims no `.fast` area and the render
block is not self-contained (`docs/FAST-AUDIO-DN.md`). Revisit if the profile is
extended. **Impact:** potentially high (SRAM vs DDR).

## 14. Store-sync gating

**Where:** `digictl_tick` runs `dn_store_sync` + `dn_store2_sync`, each
comparing 64 bytes every UI tick. Compare only every Nth tick, or short-circuit
when neither the pattern pointer nor a dirty flag changed (keep the periodic
compare for the adopt guard). **Impact:** small.

**Status: landed.** The compare runs every 8th tick when nothing is pending and
the pattern pointer is unchanged; dirty writes and pattern switches stay
immediate. Instructions −25,867 over a 1 s run; cycles neutral in `cftiming`
(instruction/bus-read win, not a cycle one). `digiemu_pattern_store.py` PASS.

## 15. Compiler flags / unroll / alignment

- `-O3 -fno-tree-loop-distribute-patterns` was **+28 % code, imports nothing**
  (usable if a measured win appears); plain `-O3` imports `memset` — **unusable**.
- Manual **2–4× loop unroll** on the hot loops (ring/EQ/fold/wave inner).
- `__attribute__((aligned(16)))` on `wv_buf` and the tables.
**Impact:** med; measure each. **Verify:** `.run`/`.bss` + `cftiming`.

**Status: rejected (flags) / deferred (unroll, alignment).** `-O3
-fno-tree-loop-distribute-patterns` on `tonefx` was measured and is a
**regression**, not a win: `.run` 27199 → 32997 (+21 %), and `cftiming` render
worst 99572 → **99971** cyc, p99 99506 → 99957, mean 99143.5 → **99536.7**,
margin 0.4026 → **0.4002**, with *more* total instructions (45,795,699 →
45,943,021) — the loop transforms pessimize the render. Reverted. The unroll and
`aligned(16)` sub-items remain: `cftiming` models instruction cycles but not
DDR/cache bursts, so alignment cannot be credited with a measured win here, and
manual unroll is speculative and code-bloating; both are parked pending a
hardware or burst-aware measurement.

---

## Explicitly out of scope here

- Changing the FX algorithms/sound (only quality/CPU trades in #9/#10/#12).
- The open bugs in `HANDOFF.md` §6/§8 (flanger/pitch link, PAGE jump, PITCH on
  note-off, microtiming, yellow LEDs) — those are separate fixes; the flanger
  flush interacts with #12, so land them together.
