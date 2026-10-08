# RingTone — Digitone mk1 release

**Master ringmod / wavefolding / EQ for the Digitone mk1.**

A set of elekloader mods for the **Digitone mk1 / Digitone Keys, OS 1.43**:
three master-insert effects, output metering, and the **DIGI FX / DIGI FOLD-EQ
pages on the master page tree (FUNC+LFO)**.

> **The packaged release lives in
> [Tone+FX](https://github.com/DigiAlchemydsp/Tone-FX/releases).** Get the
> one-file suite from there. This `releases/` folder is the older RingTone
> snapshot and is kept for reference only.

## The suite (source)

| mod | what |
|---|---|
| `digimeter` | output level metering (drawn on the DIGI FX page) |
| `digieq` | master tone tilt (low / high gain) |
| `digiring` | master ring modulator / tremolo |
| `digifold` | master wavefolder (triangle fold) |
| `digictl` | the DIGI FX and DIGI FOLD/EQ master pages, per-pattern storage and MIDI CC |

`digictl` requires the other four. The suite ships as one merged, format-2 mod,
`mods/tonefx/` (it requires the core, which it does not include), so it combines
with any other elekloader mods.

## Build from source

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "<elekloader checkout>"
$stock = "<your> Digitone_and_Digitone_Keys_OS1.43.syx"
$core  = "<elekloader>\mods\core-dn1\out\core-2.0a.elemod"
python -m elekloader.sdk.build "..\mods\tonefx" --stock $stock
python -m elekloader.patch --stock $stock --mod $core `
  --mod ..\mods\tonefx\out\tonefx-2.3c.elemod --out custom.syx --version 2.3c
```

See `../DSP.md` for the DSP reference.

Stress-tested on hardware over 3 days: **PASS** (a Digitone mk1).

Licence: GPL-2.0-or-later. Not affiliated with Elektron. Custom firmware is at
your own risk.
