# RingTone

**Master ringmod / wavefolding / EQ for the Digitone mk1.**

> **This suite has a new home: [Tone+FX](https://github.com/DigiAlchemydsp/Tone-FX/releases).**
> RingTone was the first cut; it now ships packaged as the **Tone+FX** suite
> (ring, EQ, fold, per-voice filter, meter and the DIGI pages). **Download the
> latest release from
> [github.com/DigiAlchemydsp/Tone-FX/releases](https://github.com/DigiAlchemydsp/Tone-FX/releases).**
> This repo is kept for reference until it is merged/deprecated.

![The DIGI FX page on the Digitone mk1](docs/img/digi-fx-page.png)

Unofficial, community-made [elekloader](https://github.com/irpina/elekloader)
mods for the **Elektron Digitone mk1 / Digitone Keys, OS 1.43**.

## What it is

RingTone is a **set of elekloader mods (`.elemod`) that install together**. They
process the **master mix on the Digitone's main CPU** — the same stage the
firmware runs its own effects on: after the eight FM voices have been mixed and
before that mix is handed to the analog outputs and to the USB stream. So
**every output carries them**. The FM voices themselves run on the Digitone's
**second CPU**, which these mods do not touch; they only process the mixed
audio.

The master chain is **ring → EQ → fold**, then the output meter; `digifilter`
is a **per-voice** stage instead, running before the eight FM voices are mixed:

| mod | stage | what |
|---|---|---|
| `digiring` | **ring** | a sine carrier multiplies the mix — a tremolo at a low rate, a ring at an audio rate |
| `digieq` | **EQ** | a one-pole split with low/high gains (a tone tilt) |
| `digifold` | **fold** | a triangle wavefolder, on/off + amount |
| `digifilter` | **filter** | BP / BP2 / COMB / TRASH on the selected FM voices, before the mix |
| `digimeter` | **meter** | L/R peak bars, drawn on the DIGI FX page |
| `digictl` | **pages** | the DIGI FX and DIGI FILTER master pages (FUNC+LFO) that edit the four + the meter |

`digictl` requires the other five, so **install them as a set**: build with
`core-dn1` plus all six mods.

`digifilter` hooks the render just before the voice mix (`0x4009e13e`) and
filters the chosen voices in `0x80004110` in place. The Digitone's eight voices
are **shared between the four tracks**, so routing is per voice: the DIGI FILTER
page shows eight voice toggles (trig keys 1-8) plus on/off, mode, frequency and
resonance. The voice toggles use the voice menu's voice indicator — an outlined
5x5 box, filled when the voice is routed — so they look native. See
[`docs/img/digifilter-page.png`](docs/img/digifilter-page.png).

It is built for the main CPU's budget: the cutoff and resonance are global, so
the SVF coefficients are computed **once per block** (not once per voice), the
tables are interpolated at fractional (Q8) cutoff/resonance and glide over ~5 ms
(no steps), a voice that is silent and settled is **skipped entirely**, and
routing is **capped at 4 voices**, so the per-block cost is bounded. The comb is
an integer-delay feedback comb (one multiply a sample; delay and feedback glide
once a block).

> Unofficial and unsupported. Not affiliated with, endorsed by or supported by
> Elektron. Flashing modified firmware is at your own risk. Read
> [`releases/README.md`](releases/README.md) first.

## Use

The pages live on the master page tree: **FUNC + LFO** cycles the master pages,
and our three pages are appended as the fourth, fifth and sixth entries
(DIGI FX, DIGI FILTER, DIGI FOLD / EQ). **LEFT / RIGHT** rotate our three pages
— use them if the master cycle does not reach them. PAGE keeps its stock meaning
everywhere; no stock key or encoder is taken.

- **DIGI FX** is RING only: **A** on/off, **B** depth, **C** frequency,
  **LEVEL** = meter. It draws a low-CPU ring animation (the marker circles at
  the carrier rate and jitters with the depth) and shows the depth and frequency
  amounts as vertical bars on the right border, with the output meter.
  See [`docs/img/digi-fx-page.png`](docs/img/digi-fx-page.png).
- **DIGI FOLD / EQ**: **A** FOLD on/off, **B** FOLD amount (a spiral that is a
  straight line at 0 and coils as it folds), **C** EQ LOW on/off, **D** EQ LOW
  amount, **E** EQ HIGH on/off, **F** EQ HIGH amount (faders).
  See [`docs/img/fold-eq-page.png`](docs/img/fold-eq-page.png).
- **DIGI FILTER**: **A** on/off, **B** mode (BP/BP2/COMB/TRASH), **C** frequency,
  **D** resonance, **E/F** all voices on/off, and **trig keys 1–8** toggle which
  voices are filtered. At most **4 voices** are filtered at once (the page says
  "max 4"), bounding the per-voice load; the comb is a simple integer-delay
  feedback comb.

**LEFT / RIGHT rotate the three pages** (DIGI FX → DIGI FILTER → DIGI FOLD/EQ).
No stock key or encoder is taken; PAGE keeps its stock meaning.

Every encoder/slider moves **1/127 of its range per step** (the stock
convention), so all parameters have the same speed for the same knob motion;
RESO is a 0–127 parameter too.

The master effects (EQ, ring, fold) are on by default; `digifilter` is off
until you enable it.

## Layout

```
src/            corea.h, sin256.h  (shared helpers)
mods/<id>/      mod.json + sources + out/<id>-<ver>.elemod
releases/       the packaged .elemods + a README (no firmware)
DSP.md          DSP reference (addresses, the two CPUs, the FM engine, ...)
LICENSE         GPL-2.0
```

## Getting it

elekloader builds a custom OS **on your machine** from your own stock
`Digitone_and_Digitone_Keys_OS1.43.syx` plus these mods; it never distributes
firmware. Take the `.elemod`s from [`releases/`](releases/) (plus
`core-dn1-2.0a.elemod`), add them in elekloader's window, and build the `.syx`.
See [`releases/README.md`](releases/README.md) for install and recovery.

> **New releases live in [Tone+FX](https://github.com/DigiAlchemydsp/Tone-FX/releases).**
> Get the packaged suite from there; the `releases/` folder here is the older
> RingTone snapshot.

## Building from source

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "<elekloader checkout>"
$stock = "<your> Digitone_and_Digitone_Keys_OS1.43.syx"
$core  = "core-dn1-2.0a.elemod"
foreach ($m in 'digimeter','digieq','digiring','digifold','digifilter','digictl') {
  python -m elekloader.sdk.build "mods\$m" --stock $stock
}
python -m elekloader.patch --stock $stock --mod $core `
  --mod mods\digimeter\out\digimeter-1.1.elemod --mod mods\digieq\out\digieq-1.0.elemod `
  --mod mods\digiring\out\digiring-1.0.elemod --mod mods\digifold\out\digifold-1.0.elemod `
  --mod mods\digifilter\out\digifilter-1.0.elemod --mod mods\digictl\out\digictl-1.3.elemod `
  --out custom.syx --version 2.0q
```

## Status

**Work in progress.** The FX suite is **tested on hardware** (a Digitone mk1);
all six mods are tested in the **digiemu** emulator (boot/settle,
`dsp_running=2`; both master pages draw as the fourth and fifth entries;
`digifilter`'s render hook runs live with 0 faults). `digifilter` has **not**
yet been listened to on hardware. Upcoming fixes:

- **encoder acceleration** for the parameters;
- **saving the state on the pattern level** (the settings currently reset at
  power-off);
- `digifilter`: per-track routing (the voices are shared, so v1 is per-voice),
  and a hardware audio pass.

## Testing `digifilter`

```powershell
# DSP model self-test (no toolchain)
python tests/filter_model.py

# emulator UI test: the DIGI FILTER page is present and selectable, screenshots
# (patched-Unicorn venv; --fw is a firmware the app built from core-dn1 + mods)
python tests/digiemu_digifilter.py --fw <the firmware the app built>
```

The DSP kernel is the Digitakt Digi Filter's, retuned for the Digitone's Q1.31
voice block; the render hook was exercised live in digiemu (16002 block calls,
audio engine live at 48 kHz, 0 faults).

## Licence

Our own code and docs: **GPL-2.0-or-later** ([LICENSE](LICENSE)). This does not
cover the manufacturer's firmware, which is never distributed here.
