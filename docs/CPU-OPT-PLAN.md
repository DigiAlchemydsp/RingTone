# Tone+FX BufferFX — CPU optimization plan

Scope: the whole `tonefx-buffx` suite (Core A master inserts) on the Digitone
mk1 / Keys. Goal: **lower the unit's CPU load** — idle and with all FX on — without
audible regressions except where an explicit trade is agreed.

This file is the plan. The applied-item ledger is `docs/OPTIMIZATION-ROUND.md`;
the agent/build guide is `AGENTS.md`.

## 0. The problem statement

- **Reported:** the CPU used to idle around **70 %**, now idles around **87 %**.
- The emulator's instruction model (`cftiming`) says the suite's render got
  **faster**, not slower:

  | config | 0.9x (pre-eMAC) | current exp (0.9J) |
  |---|---|---|
  | all-off (ring+EQ) | 99,682 | 98,371 |
  | + WRMZ | +8,521 | +3,835 |
  | + GRAINZ | +11,399 | +5,054 |
  | + WOB / SHFT (p99) | — | +2,805 / +4,984 |

So the idle regression is **something `cftiming` does not model**: i-cache, DDR
bursts, eMAC MACSR-switch stalls, or UI. **Diagnose before optimizing.**

## 1. Diagnose the regression (do first)

Bisect with a fixed protocol: same pattern, same page, DELAYS off, meter read
after 60 s idle.

| build | what it isolates |
|---|---|
| `0.9x` (pre-eMAC) | baseline 87 vs 70 reference |
| `0.9E`/`C` (eMAC on wrmz, s16 line) | eMAC cost |
| `0.9H` (24-bit `int` line) | line DDR traffic |
| `0.9J` (current: + Hann, x2, WOB incr, WAVe s16 pending) | full stack |
| a no-UI-anim build | RING/DELAYS drawing |

Suspects, ranked, with the hardware-only reason:

1. **eMAC MACSR mode-switch** — every handler flips `MACSR` `0xA0`→`0x20`→`0xA0`
   (6 handlers ⇒ 12 switches/block); a mode change repacks the 4 accumulators.
   `cftiming` models neither the switch nor the stall.
2. **24-bit delay line** — `wz_buf` is `int`; `cftiming` charges cycles, not DDR
   bursts.
3. **Code growth / i-cache** — `.run` 33.5 KB, eMAC inlined in every handler.
4. **UI redraw** — RING animation, DELAYS secondary slider.
5. **The delay module** itself (additive), not a regression per se.

## 2. The structural refactor (biggest lever)

Today the chain is **8 separate `ev_render_out` handlers** (ring·eq·crush·fold·
wave·wrmz·ceiling·meter). Each calls `dn_out_off()`, loads the 32-frame block,
processes it, and stores it back — the same `{L,R}` buffer is **loaded/stored
~8× per block**, plus 8 calls and 8 setups.

**Refactor: one fused subscription.** A single handler `tonefx_master_out()`
loads `{L,R}` once, runs each stage **inline** (its body as a `static inline
*_frame(l, r)` helper), and stores once. Keep each stage's true-bypass (its
`_frame` returns immediately).

- This is **not** the `CORE_AUDIO_INSERT` path that regressed +15 % — that route
  added the core's Q1.31 in/out conversions, kept the stock master running, and
  got only the block's leftover share. A fused **subscriber** on the master
  buffer has none of that.
- Keep the chain order as data (`order`) so the fused build is an option.
- Expected: ~560 fewer memory ops/block + 7 calls/setups removed. Composes with
  every micro-opt below.

## 3. eMAC policy (per §1 result)

- If MACSR churn is the cost: **set fractional mode once** in `ev_render_in`
  (order 40) and restore once at the end, instead of per handler. All suite
  modules now want the same mode.
- If the eMAC is slower on hardware for single muls: gate it behind a build flag
  and fall back to `muls.l` for the 1–2-mult sites (keep it only where it clearly
  wins, e.g. SHFT's batched interp).

## 4. Memory / lines

- **s16 wave lines** (approved): `wv_buf`/`wv_fbuf` → `short` with `<<8`/`>>8`
  scaling; halves the dominant DDR traffic. Trade: 16-bit quantization on
  WOB/FLAN/SHFT.
- **Line arena**: `wz_buf`, `wv_buf`, `wv_fbuf` in one 16-byte aligned block.
- **Downsample** the shortest-delay line (write every 2nd sample) if needed.
- 24-bit delay line: keep unless the bisect says it is the cost.

## 5. Per-module micro

- SHFT: nearest 2nd grain (trade) and/or 2× unroll WOB/FLAN/SHFT.
- Hoist remaining per-frame block constants; split any remaining per-frame
  branches (crush/fold done; check wrmz/wave).
- Meter: gated + `ff1` (done).
- Ring/EQ: eMAC (done).

## 6. UI / draw

- Cap animated redraws (`dc_rate`), cheapen the RING/DELAYS graphics, invalidate
  only on change.

## 7. Measurement protocol (no guessing)

- **Emulator**: per-module p99 (`tests/_timing_buffx.py`, `tests/_timing_wave.py`).
- **Hardware**: the §1 idle table + peak with all FX on. Every change A/B'd on
  the same clock *and* hardware-verified before it lands (the insert lesson).
- Record both in `docs/OPTIMIZATION-ROUND.md`.

## 8. Sequence

1. Bisect the regression (§1). **Do this first.**
2. Fused single-pass subscription (§2).
3. eMAC policy per the result (§3).
4. s16 wave lines + arena (§4).
5. Micro-opts and UI (§5, §6).
