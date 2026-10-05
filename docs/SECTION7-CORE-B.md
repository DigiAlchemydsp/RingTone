# Findings: Digitone section 7 (Core B) and the per-voice filter

Status: **spike / plan, not built.** Written from the OS 1.43 images
(`section_3_MAIN_OS.bin`, `section_7_BLOB.bin`) and the tooling in
`elekloader/elekloader/dsp.py`.

## Why Core B

`digifilter`'s per-voice filter currently runs on **Core A** (the main CPU), at
the render site `0x4009e13e`, on the eight voices in `0x80004110`. It is the
heaviest of the DIGI mods. Core B renders the FM voices themselves, so a filter
there would (a) take the work off the main CPU (the UI-freeze lever) and (b) be
genuinely per-voice in the engine.

## What runs where (OS 1.43)

| | Core A (main) | Core B (`section 7`, entry `0x40000b92`) |
|---|---|---|
| program | MAIN OS `0x40000400` | DSP image, loads at `0x40000400` on its bus |
| renders | effects + mix | 8 FM voices |
| render | ISR `0x4009d100` (vector 191) | vector 96 handler `0x400008fa` |
| store | output `0x80001a00` | 8 x 32 int32 at SRAM `0x80000e00` -> shared `+0x3a0` |

Core B render `0x400008fa` (measured):

```
0x400009c2  jsr 0x40003364            per-voice prep
0x400009d4  jsr 0x40003acc            FM kernel:  out 0x80000e00, in 0x80000310
0x400009ec  jsr 0x400038c2            voice state update
0x400009f6  copy 0x400 bytes  0x80000e00 -> *(arg)+0x3a0   (shared RAM)
```

The voices sit **voice-major** in `0x80000e00` (`voice v` at `+v*0x80`), the same
layout Core A reads at `0x80004110`. That is exactly the buffer `digifilter`
already filters, so the kernel carries over.

## The hook

Replace **`0x400009d4`** (`4eb940003acc`, the FM-kernel `jsr`) with
`jsr <our entry>`; our entry runs `jsr 0x40003acc`, filters `0x80000e00`, then
`rts` to `0x400009da`. (`0x400009ec`, the state update, is the other 6-byte
candidate; after it, before the copy, is equally safe.)

## Parameters: the mailbox

Core B cannot see Core A's RAM. Put a control block in **shared RAM above
`+0x7a0`** (used: params `0x000..0x39f`, voices `0x3a0..0x79f`; the DSP zeroes
the rest at boot).

| shared offset | main view | field |
|---|---|---|
| `+0x7a0` | `0x100007a0` | on, mode, freq, reso, vmask |

Core A writes it once per block (a tiny `ev_render_out` in `digifilter`, or the
existing site); Core B reads `0x7a0`.

## Code space

- Free, zeroed, unreferenced cave: **`0x4001f048-0x4001f190` = 328 bytes**
  (confirmed zero; DSP.md calls it the one validated cave).
- The SVF (`filter_dsp.s`) assembles to **200 bytes** for `-mcpu=54455`, so an
  inlined BP/BP2 SVF plus a mailbox loop *just* fits.
- **COMB/TRASH do not.** They are C on Core A today; on Core B they would need
  hand-written asm and more space than 328 B.

## Risks

1. **Real-time headroom.** Core B renders ~18.4k instructions/block and already
   runs ~80% of the second core. A full 8-voice filter adds ~4k (~+22%): a real
   risk of dropouts. An SVF-only offload is ~+10%.
2. **No linker on Core B.** `elekloader.dsp` places fixed-address `bytes`; the
   code must be position-fixed and hand-placed. Assemble with `m68k-elf-as
   -mcpu=54455`, `objcopy -O binary`, hex it into a `bytes` site.
3. **Combs need a bigger validated cave.** The 30 KB zero run at `0x40010000`
   is *workspace* (referenced), not free; it needs an emulator liveness trace.

## Action plan

1. **Mailbox + hook (no filter yet):** add the shared control block, hook
   `0x400009d4`, have the entry call `0x40003acc` and return. Build with
   `python -m elekloader.dsp`; verify in digiemu that the render count and
   `dsp_running` are unchanged and audio is bit-identical to stock.
2. **SVF-only (BP/BP2) on Core B:** inline the 200-byte SVF + a mailbox loop in
   the 328-byte cave; COMB/TRASH stay on Core A (hybrid). Verify:
   - Core B render instructions/block before/after (dropout margin);
   - 0 faults, `dsp_running=2`;
   - BP output matches the Core A kernel (`tests/filter_model.py`).
3. **COMB/TRASH:** hand-asm the comb and find a second validated cave (emulator
   liveness trace over the zero run). Only then remove the Core A path.
4. **Retire the Core A site** once Core B handles all modes.

Do **not** ship step 1 without the step 0 proof in the emulator: section 7 is a
separate engine and a bad patch is audible, not a build error.
