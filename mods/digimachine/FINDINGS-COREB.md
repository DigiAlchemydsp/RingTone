# Digi Machine — Core B findings (second CPU, section 7)

Digitone mk1 / Keys, **OS 1.43**. The wavetable engine runs on the second CPU
(the firmware's "DSP"), in parallel with the eight FM voices.
Marks: **[M]** measured from the image, **[L]** verified live, **[I]** inferred.

---

## 1. The Core B render

| item | address | note |
|---|---|---|
| section 7 load / entry word | `0x40000400` = `0x40000B92` | must not change |
| VBR | `0x40000000` | vectors -> `rte` stub `0x40000404` |
| reset / vec 96 boot | `0x40000406` | |
| **render (vector 96)** | **`0x400008FA`** | copies params in, renders 8 voices, copies audio out |
| FM kernel | `0x40003ACC` | 4 `macl` chains, 32 iterations, Q1.31 |
| per-voice prep / state | `0x40003364` / `0x400038C2` | stride `0x188` @ `0x40016934` |
| **output-copy call (hooked)** | **`0x40000A0A`** (`jsr 0x40003848`) | copies `0x400` B from `0x80000E00` -> shared `+0x3A0` |
| idle loop | `0x40000B90` | the render returns here |

The render (disassembly around `0x400009E0`):
```
400009f2  lea  %sp@(40),%sp
400009f6  pea  0x400                 ; len
400009fa  pea  0x80000e00            ; src (Core B SRAM output)
40000a00  moveal %d5,%a0
40000a02  moveal %a0@,%a1
40000a04  lea  %a1@(928),%a1         ; dst = shared +0x3A0
40000a08  movel %a1,%sp@-
40000a0a  jsr  0x40003848            ; <- the hook site
40000a10  lea  %sp@(12),%sp
```

---

## 2. The hook

`elekloader.dsp` replaces the `jsr` at **`0x40000A0A`** with a jump to the
section-7 cave **`0x4001F048`** (the only fully-unreferenced zero run, 328 B).

The engine outgrew 328 B, so the cave holds a **6-byte trampoline**
(`jmp 0x00008000`) and the **engine body is uploaded by Core A into shared RAM
at DSP `+0x8000`** and executes from there. Verified: Core B runs code from the
shared RAM and the DSP still boots (`dsp_running=2`).

`.dspmod.json` sites:
```
0x4001F048  bytes 4ef900008000  (jmp 0x00008000 trampoline)
0x40000A0A  jsr   -> 0x4001F048
```

---

## 3. Shared RAM (main `0x10000000`, DSP `0x00000000`)

128 KB dual-port. Layout used by the machine (beyond the stock structures):

```
+0x000..0x39F   stock params (main -> DSP, per-voice stride 0x9E)
+0x3A0..0x79F   stock voices (DSP -> main, 8 x 32 int32)
+0x7A0..+0x1FFFF  FREE (measured; 127 KB all zero while rendering)  [L]
+0x800..0x83F   machine params   (main -> DSP, longs)
+0x840..0x87F   machine state    (reserved)
+0x880..0x91F   machine audio    (DSP -> main, 32 stereo frames)
+0x1000..0x1FFF machine wavetables (main -> DSP once, 8 x 256 int16)
+0x8000..        machine engine image (main -> DSP once)
```

**Verified [L]:** with 2338 real Core B renders running, `+0x7A0` through
`+0x1FFFF` stayed entirely zero — free for the machine.

---

## 4. Param block (`+0x800`, longs)

| off | name | meaning |
|---|---|---|
| +0x7FC | P_MAGIC | upload-complete flag: `"DMAC"` = `0x444d4143` (Core A writes last) |
| +0x00 | P_ON | 1 = render the machine |
| +0x04 | P_INC | phase increment (~440 Hz at `39300000`) |
| +0x08 | P_DET | detune (Q14) |
| +0x0C | P_WIDTH | phase offset between readers (0..16384) |
| +0x10 | P_MORPH | table position (0..7<<8) |
| +0x14 | P_LEVEL | output gain (Q15) |
| +0x18 | P_PAN | pan (Q14) |
| +0x1C | P_FTYPE | filter type |
| +0x20 | P_FFREQ | filter freq |
| +0x24 | P_FRESO | filter reso |
| +0x28 | P_FENV | filter env depth |
| +0x2C | P_ATK | attack |
| +0x30 | P_DEC | decay |
| +0x34 | P_SUS | sustain |
| +0x38 | P_REL | release |
| +0x3C | P_GATE | note gate |

Engine state in Core B SRAM at `0x8000F800`: `PH` (+0), `PH2` (+4), `LP` (+8),
`ENV` (+12).

---

## 5. The engine (`dsp/engine.s`, 528 B)

- **Upload guard (new, 0.4)**: the engine's first action after setting MACSR is
  to read `P_MAGIC` (`+0x7FC`) and compare it to `"DMAC"` (`0x444d4143`). Core A
  writes that magic **last**, after copying the tables and engine image. If it is
  not set, the engine tail-jumps the displaced copy immediately. This is the fix
  for the Core B boot race: without it, the section-7 trampoline's `jmp
  0x00008000` executed uninitialised shared RAM on the first render and faulted
  (`access violation reading 0x10`) even with the machine off.
- **Two detuned oscillators**: `incB = incA + (incA>>14)*detune`.
- **Width**: each oscillator is read at two phases, `phase` and
  `phase + (width<<18)` -> 4 table reads.
- **Morph**: linear interpolation between table i and table i+1
  (`index` <= 6 clamp, fraction in the low byte); `d2 + ((d6-d2)*frac)>>8`.
- Four reads summed and averaged; then a **one-pole low-pass**
  (`k = 1 + (127-FFREQ)>>4`, clamp 1..8) and a **block-rate ADSR**
  (`+ATK` gated, `-REL` not; env 0..32768).
- **EMAC + `d0-d7/a0-a6` saved/restored**; sets `MACSR=0x20`; tail-`jmp` to the
  displaced copy `0x40003848`.
- L=R (pan stored, not yet applied).

**Tables** (`tables.inc`, 8 x 256 int16): sine, triangle, saw, square, pulse25,
organ, formant, metallic.

---

## 6. Cost / budget

- FM render (8 voices) ≈ **18,390 instructions/block** (measured `[L]`).
- Block = 32 frames @ 48 kHz, ~1500 blocks/s. The engine is 432 B and adds a
  small per-sample cost; measure with the live harness before hardware.

---

## 7. Gotchas

- **ColdFire:** `lsl/asr #N` only 1..8 (split longer shifts); long indexed
  addressing is `(%aN,%dN:l)` only; `movem` uses `(%sp)` not `%sp@-`; no `dbra`.
- Keep the entry word `0x40000B92`, the handshake and the `0x400008FA` render
  contract — `elekloader.dsp` refuses an entry change.
- Preserve EMAC state exactly.
- A code-only site in the zero cave must be `kind:"data"` in the spec (zero
  bytes do not decode as whole instructions).

---

## 8. Unit test

`tools/test_engine.py` (bare Unicorn, no firmware): loads the engine at
`0x00008000`, seeds a sine table, runs it. **PASS**: OFF leaves the audio slot
untouched; ON writes a **varying** waveform; registers and EMAC preserved; the
displaced copy is reached; morph=0.5 blends sine+inverted-sine to peak 0; and
**the magic guard** (ON set but no `P_MAGIC`) bails to the copy with the audio
slot untouched.
