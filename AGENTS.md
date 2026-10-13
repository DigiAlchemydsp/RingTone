# AGENTS.md — Tone+FX performance-optimization worktree

This is an **experimental worktree** of the Tone+FX dev source, branch
`perf-opt`, forked from `main` at `tonefx 3.5d`. Its purpose: reduce **CPU and
memory footprint** of the suite without changing what it does. Keep it isolated
from `main`; land changes only after they are measured and verified.

If you are an agent asked to "implement the optimizations", **read these first,
in order**, then work the plan:

| # | file | why |
|---|---|---|
| 1 | `docs/PERF-OPT-PLAN.md` | the full optimization list: targets, impact, risk, verification |
| 2 | `docs/PERF-OPT-INSTRUCTIONS.md` | the step-by-step procedure, measurement protocol, commit discipline |
| 3 | `docs/OPTIMIZATION.md` | the DSP/CPU/footprint ledger + methods already used |
| 4 | `DSP.md` | Core A/B addresses, the render model, fixed-point conventions |
| 5 | `HANDOFF.md` | session state + open bugs — **in the MAIN worktree** (`../digitone_corea/HANDOFF.md`), gitignored so it is not in this one |
| 6 | `docs/PATTERN-STORAGE.md` | the per-pattern store (block 1 `DGX1` v10, block 2 `DGX2`) |
| 7 | `docs/MIDI-CC.md` | the CC map + the `0x400ED94E` hook |
| 8 | `mods/tonefx/README.md` | how the suite is packaged (one format-2 mod) |
| 9 | `../elekloader-modding-guide/03-hook-bus-and-events.md` | the event model (`ev_render_in/out`, `ev_tick`, …) |
| 10 | `../elekloader-modding-guide/plans/digitone-dsp.md` | the Core A render map (buses, eDMA, addresses) |

## Hard constraints (a change that breaks one is rejected)

- **No libc, no FPU.** All integer. The build must report **`imports nothing`**.
- No 64-bit multiply helpers; keep products inside 32 bits (`dn_mul15`/`dn_mul14`
  in `src/corea.h` show the exact pattern).
- **Subscription-only**: FX are `ev_render_in`/`ev_render_out` handlers; never
  patch a stock instruction (the `core` mod owns the sites).
- The render is **interrupt level**, 1500 blocks/s; keep handlers short. If you
  use the **EMAC**, leave `MACSR` as found (the core saves/restores it).
- Never change audible behaviour unless the plan says it is a deliberate
  quality/CPU trade (delay-line downsample/12-bit).
- Do not commit firmware; `*.syx`, `*.elemod`, `testout/` are gitignored.

## Build & test (this machine)

```powershell
$env:PATH="C:\SysGCC\m68k-elf\bin;"+$env:PATH; $env:ELEKLOADER_CROSS="m68k-elf-"
$env:PYTHONPATH="C:\Users\benan\Music\ELEKTRON\elekloader"
$stock="C:\Users\benan\Music\ELEKTRON\Digitone_and_Digitone_Keys_OS1.43.syx"
python -m elekloader.sdk.build "mods\tonefx" --stock $stock
python -m elekloader.patch --stock $stock `
  --mod "C:\Users\benan\Music\ELEKTRON\elekloader\mods\core-dn1\out\core-2.0a.elemod" `
  --mod "mods\tonefx\out\tonefx-3.5d.elemod" --out "testout\test-3.5d.syx" --version 3.5d
```

Regression tests (patched-Unicorn venv, `C:\Users\benan\AppData\Local\Temp\opencode\digiemu-venv`):
`digiemu_pattern_store.py`, `digiemu_midi_cc.py --map …map.json`, `_diag_perf.py`,
`_diag_macros.py`, `_diag_wavesplit.py`, `_diag_macro_store.py`; live:
`_diag_perf_live.py`, `_diag_wash_live.py`, `_diag_radio_live.py`,
`_diag_flaflush.py`. The patch writes `testout\test-3.5d.syx.map.json` with every
symbol's absolute address — read it, never guess RAM offsets.

## Working rules

1. **One optimization at a time**, each in its own commit, message prefixed
   `perf:`. Measure before/after (`docs/PERF-OPT-INSTRUCTIONS.md` §Measuring).
2. After each: build clean (`imports nothing`), run the regression set, and note
   the numbers in `docs/OPTIMIZATION.md` (ledger) and `HANDOFF.md`.
3. If a change risks audio, A/B it live (real SSI) and say so.
4. Keep `docs/PERF-OPT-PLAN.md` updated with status per item.
