# RingTone

**Master ringmod / wavefolding / EQ for the Digitone mk1.**

> **This suite has a new home: [Tone+FX](https://github.com/DigiAlchemydsp/Tone-FX/releases).**
> RingTone was the first cut; it now ships packaged as the **Tone+FX** suite
> (ring, EQ, fold, meter and the DIGI pages). **Download the
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

The master chain is **ring → EQ → fold**, then the output meter:

| mod | stage | what |
|---|---|---|
| `digiring` | **ring** | a sine carrier multiplies the mix — a tremolo at a low rate, a ring at an audio rate |
| `digieq` | **EQ** | a one-pole low/high split (a low-shelf / high-shelf) |
| `digifold` | **fold** | a triangle wavefolder with CLEAN/MUD/DIST/TRSH fold modes + an internal overdrive |
| `digimeter` | **meter** | L/R peak bars, drawn on the DIGI FOLD page |
| `digictl` | **pages** | the RING / FOLD / TILT master pages (FUNC+LFO) that edit the three + the meter |

`digictl` requires the other four, so **install them as a set**: build with
`core-dn1` plus all five mods.

> Unofficial and unsupported. Not affiliated with, endorsed by or supported by
> Elektron. Flashing modified firmware is at your own risk. Read
> [`releases/README.md`](releases/README.md) first.

## Use

The pages live on the master page tree: **FUNC + LFO** cycles the master pages,
and our three pages are appended after the stock ones. **LEFT / RIGHT** (or the
on-screen `<` `>` arrows) rotate the whole master page list; the stock top
status bar stays above every page. PAGE keeps its stock meaning everywhere; no
stock key or encoder is taken.

- **RING** — **A** on/off, **E** depth, **F** frequency. A centred ring
  animation (the marker circles at the carrier rate and jitters with the
  depth), the depth/frequency bars on the right and the values bottom-left.
- **FOLD** — **A** on/off, **D** fold type, **E/F/G/H** amount. The spiral (a
  straight line at 0 that coils as it folds), the big mode title, and the
  amount as a vertical slider next to the L/R meter.
- **TILT** — **A** on/off, **E** low shelf, **H** high shelf. A bent low/high
  response curve.

The **fold type** is a continuous 0–127 knob spread over four modes — CLEAN
(36% fold), MUD (full fold), DIST (36% fold + hard-clip overdrive) and TRSH
(full fold + overdrive) — interpolated between modes and capped at CLEAN/TRSH.

Every parameter is **0–127** and moves **one step per notch**, the stock
convention (EQ LOW/HIGH show 0–127 with 64 = flat). The FX also respond to
**incoming MIDI CC** (a set of CC numbers the stock DN does not use), so they can
be played/sequenced from an external controller; see
[`docs/MIDI-CC.md`](docs/MIDI-CC.md).

The master effects (EQ, ring, fold) are on by default.

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
  --mod mods\tonefx\out\tonefx-2.3c.elemod --out custom.syx --version 2.3c
```

The components (`digimeter`, `digieq`, `digiring`, `digifold`, `digictl`) can
still be built and combined individually.

## Status

**Work in progress.** The suite is stress-tested on real hardware over 3 days:
**PASS** (a Digitone mk1) and in the **digiemu** emulator (boot/settle,
`dsp_running=2`; the master pages draw; per-pattern persistence and the MIDI-CC
hook are tested). Done:
pattern-level save/reload, stock 0–127 controls, MIDI CC, one merged `tonefx`
mod, and encoder steps that now match stock (one step per encoder detent, with
the driver's own acceleration). Remaining:

- a **hardware audio pass** of the FX themselves;
- small UI polish.

## Parked / future work (branches + docs; NOT in the release)

The release (`Tone+FX` 2.3c) is the ring / EQ / fold / meter suite + MIDI CC only.
These are parked for later:

- **Sequencer p-lock automation for the FX params** — branch `tonefx-plock`,
  `docs/PLOCK-AUTOMATION.md` (on the branch): let the internal sequencer
  record/play the DIGI FX params as parameter locks. Prototype works; needs the
  active-page global (the ~1/4-page issue), then a hardware pass.
- **Per-voice filter rewrite + digimachine** — branch `filter-and-digimachine`:
  the Digitakt-style smoothed/fractional comb with four knobs, and the wavetable
  machine. Not part of Tone+FX.
- **LFO destinations** — `docs/MODULATION-AND-ROUTING.md` (parked bridge).
- **Audio-chain reroute (pre-FX)** — same doc.
- **Core B per-voice filter** — parked with the filter branch.
- **FAST AUDIO on the DN** — `docs/FAST-AUDIO-DN.md`.

## Testing

```powershell
python tests/digiemu_fx_screenshots.py --fw <dn1-...>               # RING / FOLD / TILT screenshots
python tests/digiemu_nav.py --fw <dn1-...>                          # LEFT/RIGHT page navigation
python tests/digiemu_pattern_store.py --fw <dn1-...>                # per-pattern settings
python tests/digiemu_midi_cc.py --fw <dn1-...> --map <syx.map.json> # MIDI CC hook
```

(The `digiemu_*` tests need the patched-Unicorn venv; `--fw` is a firmware the
app built from `core-dn1` + the mods.)

## Licence

Our own code and docs: **GPL-2.0-or-later** ([LICENSE](LICENSE)). This does not
cover the manufacturer's firmware, which is never distributed here.
