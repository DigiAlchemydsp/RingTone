# Digi FX — Digitone mk1 release

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
| `*.syx.json`, `*.syx.map.json` | build manifest and symbol map |

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

## Use

- **FUNC + LFO** cycles the master pages; the **fourth entry** is **DIGI FX**.
- Encoders **A–H** edit: EQ on, EQ low, EQ high, ring on, ring depth, ring
  frequency, fold on, fold amount. **LEVEL** toggles the meter.
- **Signal order** on the master mix: **ring → EQ → fold**.
- The four effects are **on by default**: a gentle EQ tilt, ring at 90 Hz / 40%,
  fold at amount 0 (1.0x, no fold), and the L/R meter bars on the right of the
  page.

## Status and caveats

- Tested in the **digiemu** emulator (boots, settles, `dsp_running=2`; the page
  draws as the fourth master entry). **Not yet tested on hardware.**
- **Settings are not saved per pattern yet** — they reset at power-off. Per-pattern
  persistence (in the kit) is the open item; see `../HANDOFF.md` §6.
- The DIGI FX page is opened by FUNC+LFO; the emulator's key-injection harness
  cannot cycle repeated same-key chords, so the page was verified structurally.

## Build from source

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "C:\Users\benan\Music\ELEKTRON\elekloader"
$stock = "C:\Users\benan\Music\ELEKTRON\Digitone_and_Digitone_Keys_OS1.43.syx"
$core  = "C:\Users\benan\Music\ELEKTRON\elekloader-main\build\cores\core-dn1-2.0a.elemod"
foreach ($m in 'digimeter','digieq','digiring','digifold','digictl') {
  python -m elekloader.sdk.build "..\mods\$m" --stock $stock
}
python -m elekloader.patch --stock $stock --mod $core `
  --mod ..\mods\digimeter\out\digimeter-1.1.elemod --mod ..\mods\digieq\out\digieq-1.0.elemod `
  --mod ..\mods\digiring\out\digiring-1.0.elemod --mod ..\mods\digifold\out\digifold-1.0.elemod `
  --mod ..\mods\digictl\out\digictl-1.2.elemod --out Digitone_OS1.43-digifx.syx --version 2.0o
```

See `../DSP.md` for the DSP reference and `../HANDOFF.md` for the session state.

Licence: GPL-2.0-or-later. Not affiliated with Elektron. Custom firmware is at
your own risk.
