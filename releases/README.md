# RingTone — Digitone mk1 release

**Master ringmod / wavefolding / EQ for the Digitone mk1.**

A set of elekloader mods for the **Digitone mk1 / Digitone Keys, OS 1.43**:
three master-insert effects, output metering, and a **DIGI FX page on the master
page tree (FUNC+LFO, fourth entry)** that controls them.

| file | what |
|---|---|
| `Digitone_OS1.43-digifx.syx` | **flashable** custom OS; unit shows **`2.0o`** |
| `core-dn1-2.0a.elemod` | the required core (the hook bus) |
| `digimeter-1.1.elemod` | output level metering (drawn on the DIGI FX page) |
| `digieq-1.0.elemod` | master tone tilt (low/high gain) |
| `digiring-1.0.elemod` | master ring modulator / tremolo |
| `digifold-1.0.elemod` | master wavefolder (triangle fold) |
| `digictl-1.2.elemod` | the DIGI FX master page that edits the three + meter |
| **`digifilter-1.0.elemod`** | **per-voice filter: BP / BP2 / COMB / TRASH (new)** |
| **`digictl-1.3.elemod`** | **adds the DIGI FILTER page + PAGE toggle (new)** |
| `*.syx.json`, `*.syx.map.json` | build manifest and symbol map |

> The `*.syx` in the table above is the last packaged build (`2.0o`). The new
> `digifilter` / `digictl-1.3` (and the noise/CPU fixes to `digieq`/`digiring`/
> `digifold`) are tested in digiemu (`2.0u`) but not yet in a packaged `.syx`;
> build one from source with the six mods (see below) or add the `.elemod`s to
> your existing set in elekloader.

Latest test set (emulator `2.1h`):

```
core-dn1-2.0a.elemod   7a0aec0ae791fa41740d06403caab9fc84c32c821a28441fe6cb23750260f194
digimeter-1.1.elemod   31976227fc377dbd6d54c8e28e3e3d1ff58dd53a7d3306294e96f8eb99e7aec5
digieq-1.0.elemod      d86225361c2827164cd9ef476e856a15973a08948bb2daa66e8be84ee6ef676c
digiring-1.0.elemod    2db59bd30427032eabc90c0b0dc8fec0a128b71b82b3bf6ccbb0a554c351dff0
digifold-1.0.elemod    121b45ec6db41d03492040f1c070d5b20839ba8e1f89a2970eece83be638222e
digifilter-1.0.elemod  de4ac6ae1f70d5d9250c7ff0ee7c65ac25ae6ef9d2f150924fc5bca092ff4e10
digictl-1.3.elemod     1ce8594d4cdcbfafe0e23aef961b7cdc2ee0fad877d5e87d01763f0b2d17a555
```

Every encoder/slider moves **1/127 of its range per step**, so all parameters
have the same speed for the same knob motion (and the filter's RESO is a
0..127 param again, like the stock page).

`digictl-1.2.elemod` is superseded by `digictl-1.3` — use **1.3**.

**`Digitone_OS1.43-digifx.syx`** sha256
`32d569fcbe90849f2f50c3fb7f8536abf78d819c66e95328f38cea3a4138a4b1`
(1,828,896 bytes). Built from `Digitone_and_Digitone_Keys_OS1.43.syx` with
`core-dn1-2.0a`; only the main OS (section 3) changes — every other section is
the stock file's, byte for byte. No firmware is distributed here.

## Install

1. Connect the unit over USB, open **Elektron Transfer**, select and connect.
2. Drag `Digitone_OS1.43-digifx.syx` onto the drop area, press **YES** on the
   unit. Do not power off until it finishes.

**Recovery** (the bootloader is never changed): hold **FUNC** while powering on
for the startup menu, press **TRIG 4 (OS UPGRADE)**, then send the stock
`Digitone_and_Digitone_Keys_OS1.43.syx` with Transfer's legacy OS upgrade mode.

## Digi Machine (wavetable machine) — 2.4a

`Digitone_OS1.43-digimachine.syx` is a **separate** custom OS that hosts a
wavetable machine on the synth tracks' **SYN1 algorithm slots 8..15**. It is
built from `core-dn1-2.0a` + `digimachine-0.6.elemod` +
`digimachine.dspmod.json` (Core B), and **not** combined with the DIGI FX mods
above. The unit shows **`2.4a`**.

- sha256 `8b707ef0402a2bc04e3d9df99ebd0a58c6534a44f4e523c7917bbe1ec8baf4c5`
  (1,831,072 bytes); only section 3 (main OS) and section 7 (second CPU) differ
  from stock; sections 2/4/5/6/8 are stock byte for byte.
- **Verified in digiemu**: boots and settles (`dsp_running_u32=2`, 0 faults);
  the engagement path is proven end to end (algorithm >= 8 -> shared P_ON=1 ->
  the Core B engine writes 64/64 non-zero audio frames; restoring an FM
  algorithm -> P_ON=0).
- **Stage-1 limitations**: the FM voice for slots 8..15 is **not skipped** (the
  real FM-skip site is unknown); per-note pitch is not wired (gate follows the
  transport, pitch is the SYN page tune); no machine UI (the SYN pages are the
  interface); the gesture that selects algorithm 8..15 on the stock SYN1 page is
  **not yet confirmed**. See `mods/digimachine/HW-TEST.md` before flashing.
- Build: `mods/digimachine/HANDOFF.md` §3.

## Use

- **FUNC + LFO** cycles the master pages; our three pages are appended as the
  **fourth, fifth and sixth** entries: **DIGI FX**, **DIGI FILTER**,
  **DIGI FOLD / EQ**.
- On our pages, **RIGHT** / **LEFT** rotate the three pages (use them if the
  master cycle does not reach them). PAGE keeps its stock meaning.
- **DIGI FX** is **RING only**: **A** on/off, **B** depth, **C** frequency,
  **LEVEL** meter. It draws a low-CPU ring animation and the depth/frequency
  amounts as vertical bars on the right border.
- **DIGI FOLD / EQ**: **A** FOLD on/off, **B** FOLD amount (a spiral that is a
  straight line at 0 and coils as it folds), **C** EQ LOW on/off, **D** EQ LOW
  amount, **E** EQ HIGH on/off, **F** EQ HIGH amount (faders).
- **DIGI FILTER**: **A** on/off, **B** mode (BP/BP2/COMB/TRASH), **C** freq,
  **D** reso, **E/F** all voices on/off; **trig keys 1-8** route/unroute each
  voice (routed = filled). At most **4 voices** are filtered at once (the page
  says "max 4"); the comb is a simple integer-delay feedback comb. It is
  **off by default**; enable with **A**.
- **Signal order** on the master mix: **ring -> EQ -> fold**; the filter runs
  per-voice, before the mix.
- The EQ, ring and fold are **on by default** (a gentle EQ tilt; ring at
  90 Hz / 40%; fold at amount 0, which is exact bypass).

## Status and caveats

- **Tested on hardware** (a Digitone mk1) and in the **digiemu** emulator (boots,
  settles, `dsp_running=2`; the page draws as the fourth master entry).
- **Settings are not saved per pattern yet** — they reset at power-off.
  Per-pattern persistence (in the kit) is the open item.
- The DIGI FX page is opened by FUNC+LFO; the emulator's key-injection harness
  cannot cycle repeated same-key chords, so the page was verified structurally.

## Build from source

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "C:\Users\benan\Music\ELEKTRON\elekloader"
$stock = "C:\Users\benan\Music\ELEKTRON\Digitone_and_Digitone_Keys_OS1.43.syx"
$core  = "C:\Users\benan\Music\ELEKTRON\elekloader-main\build\cores\core-dn1-2.0a.elemod"
foreach ($m in 'digimeter','digieq','digiring','digifold','digifilter','digictl') {
  python -m elekloader.sdk.build "..\mods\$m" --stock $stock
}
python -m elekloader.patch --stock $stock --mod $core `
  --mod ..\mods\digimeter\out\digimeter-1.1.elemod --mod ..\mods\digieq\out\digieq-1.0.elemod `
  --mod ..\mods\digiring\out\digiring-1.0.elemod --mod ..\mods\digifold\out\digifold-1.0.elemod `
  --mod ..\mods\digifilter\out\digifilter-1.0.elemod --mod ..\mods\digictl\out\digictl-1.3.elemod `
  --out Digitone_OS1.43-digifx.syx --version 2.0t
```

See `../DSP.md` for the DSP reference.

Licence: GPL-2.0-or-later. Not affiliated with Elektron. Custom firmware is at
your own risk.
