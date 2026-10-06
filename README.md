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

Every parameter is **0–127** and moves **one step per notch**, the stock
convention (so EQ LOW/HIGH show 0–127 with 64 = flat; RESO is 0–127 too). The
FX also respond to **incoming MIDI CC** (a set of CC numbers the stock DN does
not use), so they can be played/sequenced from an external controller; see
[`docs/MIDI-CC.md`](docs/MIDI-CC.md).

The master effects (EQ, ring, fold) are on by default; `digifilter` is off
until you enable it.

## Layout

```
src/            corea.h, sin256.h  (shared helpers)
mods/<id>/      mod.json + sources + out/<id>-<ver>.elemod
mods/tonefx/    the merged suite mod (format 2; requires the core, no core inside)
releases/       the packaged .elemods + a README (no firmware)
docs/           findings (pattern storage, MIDI CC, parked DSP plans)
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

The suite ships as one merged mod, `mods/tonefx/` (it requires the core, which
it does not include). Build it, then patch the core + `tonefx`:

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "<elekloader checkout>"
$stock = "<your> Digitone_and_Digitone_Keys_OS1.43.syx"
$core  = "<elekloader>\mods\core-dn1\out\core-2.0a.elemod"
python -m elekloader.sdk.build "mods\tonefx" --stock $stock
python -m elekloader.patch --stock $stock --mod $core `
  --mod mods\tonefx\out\tonefx-2.3b.elemod --out custom.syx --version 2.3b
```

The components (`digimeter`, `digieq`, `digiring`, `digifold`, `digifilter`,
`digictl`) can still be built and combined individually.

## Status

**Work in progress.** The suite is stress-tested on real hardware (a Digitone
mk1) and in the **digiemu** emulator (boot/settle, `dsp_running=2`; the master
pages draw; per-pattern persistence and the MIDI-CC hook are tested). Done:
pattern-level save/reload, stock 0–127 controls, MIDI CC, one merged `tonefx`
mod, and encoder steps that now match stock (one step per encoder detent, with
the driver's own acceleration). Remaining:

- a **hardware audio pass** of the FX themselves;
- small UI polish;
- `digifilter`: per-track routing (the voices are shared, so v1 is per-voice).

## Testing

```powershell
python tests/filter_model.py                                        # DSP model (no toolchain)
python tests/digiemu_digifilter.py  --fw <dn1-...>                  # FILTER page + render hook
python tests/digiemu_fx_screenshots.py --fw <dn1-...>               # RING/COMB/FOLD screenshots
python tests/digiemu_pattern_store.py --fw <dn1-...>                # per-pattern settings
python tests/digiemu_midi_cc.py --fw <dn1-...> --map <syx.map.json> # MIDI CC hook
```

(The `digiemu_*` tests need the patched-Unicorn venv; `--fw` is a firmware the
app built from `core-dn1` + the mods.)

The `digifilter` DSP kernel is the Digitakt Digi Filter's, retuned for the
Digitone's Q1.31 voice block; the render hook was exercised live in digiemu
(16002 block calls, audio engine live at 48 kHz, 0 faults).

## Licence

Our own code and docs: **GPL-2.0-or-later** ([LICENSE](LICENSE)). This does not
cover the manufacturer's firmware, which is never distributed here.
