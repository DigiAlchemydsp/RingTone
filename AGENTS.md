# AGENTS.md — Tone+FX (Digitone source, 4.0c)

Guide for AI agents working in this repo. Read this first, then
`docs/CPU-OPT-PLAN.md` (the plan) and `docs/OPTIMIZATION-ROUND.md` (the applied
ledger). The release repo (`Tone+FX/`) carries `HANDOFF.md`, the built elemods
and the Digitakt port.

## Hard rules

- **This tree is the Digitone build source.** Work here for the Digitone. The
  release repo (`Tone+FX/`) is edited only for the vendored Digitakt port and the
  release artifacts, when the task asks for it. Do not edit `digitone_corea`,
  `digi1_mods*` or `elekloader*` unless the task says so.
- **`imports nothing` is a hard constraint.** The build must report
  `imports nothing` (no libc, no `memcpy`/`memset`, no 64-bit multiply helper).
  If a change adds an import, it is wrong.
- **The target has no FPU.** All DSP is integer fixed-point.
- **Never commit/push** unless explicitly asked.
- **Measure, don't assume.** Every render/perf change goes through the emulator
  timing harness and, for anything structural, a hardware pass (see the
  `CORE_AUDIO_INSERT` lesson in `docs/OPTIMIZATION-ROUND.md` §12.3).

## What this is

The **Tone+FX suite** (ring, EQ/tilt, crush, fold, wave PITCH/STEREO) plus **one
buffer-FX module** (`digiwrmz`: WRMZ modulated delay + GRAINZ granular), running
as **subscription-only master inserts** on **Core A** of a **Digitone mk1**
(2× ColdFire **MCF5441x**, `eMAC`). OS **1.43 / 1.44**. One elemod per device+OS.

- Chain (permanent): ring 50 → EQ 55 → crush 57 → fold 60 → **PITCH 61 →
  WRMZ 62 → STEREO 63** → ceiling 64 → meter 65. The WAVE insert is split into
  `digiwave_pitch_render_out` / `digiwave_stereo_render_out` so the delay always
  sits between PITCH and STEREO.
- 32 stereo frames/block, 48 kHz, 1500 blocks/s; samples are **int32, 24-bit
  left-justified** (`|sample| ≤ 2^23`).

## Environment (once per shell)

```powershell
$env:PATH="C:\SysGCC\m68k-elf\bin;"+$env:PATH
$env:ELEKLOADER_CROSS="m68k-elf-"
$env:PYTHONPATH="C:\Users\benan\Music\ELEKTRON\00 ELEKLOADER NEW\elekloader-main"
$s143="C:\Users\benan\Music\ELEKTRON\Digitone_and_Digitone_Keys_OS1.43.syx"
$s144="C:\Users\benan\Music\ELEKTRON\Digitone_and_Digitone_Keys_OS1.44.syx"
$c143="C:\Users\benan\Music\ELEKTRON\00 ELEKLOADER NEW\core-dn1-4.0.elemod"
$c144="C:\Users\benan\Music\ELEKTRON\digitone_corea\dist\core-dn1-4.0-os1.44.elemod"
```

Toolchain: GCC 4.8 / binutils 2.23, `-mcpu=54455` (EMAC-capable). GCC **does not
emit EMAC** — the eMAC is used only through inline asm in `src/emac.h`.

## Build · lint · patch

```powershell
python -m elekloader.sdk.build "mods\tonefx" --stock $s143      # -> mods\tonefx\out\tonefx-<ver>.elemod
python -m elekloader.lint  "mods\tonefx\out\tonefx-0.9x.elemod" --stock $s143 --with $c143
python -m elekloader.patch --stock $s143 --mod $c143 `
  --mod "mods\tonefx\out\tonefx-0.9x.elemod" --out "testout\exp-1.43.syx" --version 0.9X
```

- `--version` must be **exactly 4 ASCII chars**.
- Build for 1.44 by passing `--stock $s144`; patch 1.44 with `$c144`.
- `elekloader.patch` writes `<out>.syx.map.json` (symbol map for the emulator
  tests) next to the syx.

## Emulator (patched-Unicorn venv)

```powershell
$py="C:\Users\benan\AppData\Local\Temp\opencode\digiemu-venv\Scripts\python.exe"
$env:PYTHONPATH="C:\Users\benan\Music\ELEKTRON\digiemu-main"
& $py -m emu.portable --add "testout\exp-1.43.syx" --yes      # -> fw dir dn1-<ver>-<sha8>, boot/settle
```

Then run a harness with the fw dir name and the map json:

```powershell
$env:DIGIEMU="C:\Users\benan\Music\ELEKTRON\digiemu-main"
& $py tests\_timing_buffx.py --fw dn1-0.9j-7b3fd534 --map testout\exp3-1.43.syx.map.json --ms 120
& $py tests\_timing_wave.py  --fw <fw> --map <map> --ms 120
& $py tests\_diag_buffx_live.py --fw <fw> --map <map>          # real SSI renders, 0 faults
& $py tests\_probe_mix.py --fw <fw> --map <map>                # drives WOB/SHFT/FLAN/WIDE
& $py tests\_cap_buffx.py --fw <fw>                            # ASCII panel dump (RING/DELAYS)
```

## Fixed-point conventions

- `src/corea.h` — `dn_q15`, `dn_mul15`, `dn_mul14` (C fallbacks, exact
  `(x*c)>>k` two-term form).
- `src/emac.h` — eMAC inline asm: `bx_mul15/14/12/8/14w`, `bx_mul15x2`,
  `bx_q8`, `bx_lp_e`, `bx_dc_e`, and the MACSR discipline
  (`bx_macsr_save/frac/restore`). In signed-fractional mode (`MACSR=0x20`)
  `movclr.l(mac.l Y,X) == (Y*X)>>31`, so `bx_mul15(x,c) = (x*(c<<16))>>31 = (x*c)>>15`.
- **MACSR discipline:** the core saves/restores the EMAC around the render; a
  handler must call `bx_macsr_save()` then `bx_macsr_frac()` before its MACs and
  `bx_macsr_restore()` after (no `return` in between). `bx_macsr_frac` clears
  ACC0-3; every helper leaves ACC0 at 0.
- `src/buffx.h` — shared buffer-FX primitives: `bx_wet` (wet-mix cap **0.75**),
  `bx_read_at` (24-bit interpolated read), `bx_soft` (soft clip), `bx_inc_mhz`
  (sub-Hz LFO), `bx_sin`, `bx_lp/bx_dc`, `bx_sat16`, `BX_K`.

## Parameter / store model

- Global `int` params (e.g. `digiwave_mix`, `digiwrmz_fb`) edited by `digictl`.
- Per-pattern store: all 51 params packed into **one reserved MIDI track**,
  t=7 at `pattern+0x1BB0`, magic `"DGX4"` (`dn_stbits` gives 1-7 bits each);
  reserve that track on **MIDI channel 16**. The old `DGX1/2/3` blocks at
  `pattern+0x1040/+0x1410/+0x17E0` (channels 1-3) are never read or written —
  a configured MIDI track writes its channel/page there. See
  `docs/PATTERN-STORAGE.md`.
- MIDI CCs: ring 8/11/36, crush 20–23, wave 24–32, fold 37/40/41, eq 67–69,
  delays 80–87.
- UI pages are kinds appended to the master view vector (`digictl.c`); RING kind
  0, DELAYS kind 11.

## Current state (4.0c, released)

**Tone+FX 4.0c** is released (GitHub `DigiAlchemydsp/Tone-FX`, tag `v4.0c`):
four elemods for Digitone 1.43/1.44 and — via the vendored port — Digitakt
1.53/1.54. This tree builds the **Digitone** side; the DT port is at
`Tone+FX/DIGITAKT PORT/digi1_mods-main/mods/tonefx/`.

Digitone build (the release "comb" config): `.run 25,594`, `.bss 47,182`,
11 sites, 970 relocs, **`imports nothing`**. Layout: `mods/` (modules +
`mod.json`), `src/` (shared headers), `tests/` (emulator harnesses), `docs/`,
`dist/` (cores), `testout/` (syx + staged elemods). Delays: mono **s16** line,
`WZ_N=2^14` (0.34 s). The 4.0b/4.0c work (store, macros, chain, WASH CPU) is in
`HANDOFF.md`.

- **`-DBX_EMAC_HOISTED=1`** (suite `mod.json` cflags, top level + 1.44 port):
  `digictl_macsr_begin/end` (ev_render_out order 49/74) flip the eMAC to fractional
  once per block; handlers use `bx_emac_enter/leave` (`src/emac.h`).
- **`-DBX_S16_LINE=1`** and **`-Os`**: the release config (s16 delay line;
  size-optimised). **`-DBX_NO_EMAC=1`**, **`-DBX_NO_UI_ANIM=1`**,
  **`-DBX_FULL_FLUSH=1`**: A/B knobs. See `docs/OPTIMIZATION-ROUND.md` §10–§12.

## Task

4.0c is shipped. The current task is the **in-depth review + next optimization
round** (see `HANDOFF.md` §4): the WASH delay cost (half-rate wet / mono WOB /
delay-time cap), 4-accumulator MAC interleaving on the hottest loops, eMAC on
`fold`/`crush` Q8 and WAVE WIDE, and a review of `dn_store_sync`, the macro
capture/restore, and the split WAVE passes. The earlier idle **70 % → 87 %**
question is still open (the eMAC A/B was decided on hardware; the delay line /
i-cache / UI redraw remain suspects). See `docs/CPU-OPT-PLAN.md` and the ledger
`docs/OPTIMIZATION-ROUND.md`.
