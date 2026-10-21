# Tone+FX — development source

**A master effect suite for the Digitone mk1 / Digitone Keys (OS 1.43 and 1.44).**

> This is the **development/source** repo (remote still named `RingTone`). The
> **release** repo — built `.elemod`s, docs and packaged releases — is
> [Tone+FX](https://github.com/DigiAlchemydsp/Tone-FX/releases). **Download the
> latest release from
> [github.com/DigiAlchemydsp/Tone-FX/releases](https://github.com/DigiAlchemydsp/Tone-FX/releases).**

![The RING page on the Digitone mk1](docs/img/ui-ring.png)

Unofficial, community-made [elekloader](https://github.com/irpina/elekloader)
mods for the **Elektron Digitone mk1 / Digitone Keys, OS 1.43 / 1.44**. (A
community port of the same suite for the **Elektron Digitakt mk1, OS 1.53 /
1.54** is maintained by **gdeo607** in `digi1_mods`, vendored in the release repo
under `DIGITAKT PORT/`.)

## What it is

Tone+FX is a **set of elekloader mods (`.elemod`) that install together**. They
process the **master mix on the Digitone's main CPU** — the same stage the
firmware runs its own effects on: after the eight FM voices have been mixed and
before that mix is handed to the analog outputs and to the USB stream. So
**every output carries them**. The FM voices themselves run on the Digitone's
**second CPU**, which these mods do not touch.

Permanent chain:

```
ring → EQ → crush → fold → PITCH → DELAYS (WRMZ/GRAINZ) → STEREO → ceiling → meter
```

| mod | stage | what |
|---|---|---|
| `digiring` | **ring** | a sine carrier multiplies the mix — tremolo at a low rate, ring at an audio rate |
| `digieq` | **EQ** | a one-pole low/high split (low shelf / high shelf) |
| `digicrush` | **crush** | Crunch / Redux: bit-reduce (BITS), sample-rate hold (SR), or a hard-clip drive (CRUNCH) |
| `digifold` | **fold** | triangle wavefolder with CLEAN/MUD/DIST/TRSH fold modes + internal overdrive |
| `digiwave` | **PITCH / STEREO** | one modulation engine, two pages: **PITCH** (WOB, SHFT) and **STEREO** (FLAN, PAN, WIDE); split into two passes so the delay sits between them |
| `digiwrmz` | **DELAYS** | one mono s16 delay line, two modes: **WRMZ** (modulated delay) and **GRAINZ** (three drifting taps) |
| `digimeter` | **meter** | L/R peak bars, drawn on the DIGI FOLD/CRUSH pages |
| `digictl` | **pages / store / CC** | the twelve master pages, the four macros, the per-pattern store and the MIDI CC hook |

`digictl` requires the FX mods, so **install them as a set** (build with
`core-dn1` 4.0 plus the suite, or just `mods/tonefx`).

> Unofficial and unsupported. Not affiliated with, endorsed by or supported by
> Elektron. Flashing modified firmware is at your own risk. No firmware is
> distributed here.

## Use

The pages live on the master page tree: **FUNC + LFO** opens it.

- **Main scroll** (**LEFT / RIGHT**): the stock master pages, then our FX pages
  in play order **FOLD - CRUSH - RING - STEREO - PITCH - TILT - DELAYS**.
- **Macro tree** (**UP**): **PERFORM - WASH - RADIO - DESTROY - SPACE**
  (LEFT/RIGHT cycle within it; **UP** returns to the FX page you left).

The stock top status bar stays above every page. PAGE keeps its stock meaning;
no stock key or encoder is taken. A page whose section is off draws a framed
**OFF** box; a page driven by a macro draws a **MACRO** box. **FUNC + an encoder
turn snaps that parameter to 0 % / 100 %**.

- **RING** — A on/off, E depth, F frequency.
- **FOLD** — A on/off, D fold type, E/F/G/H amount, LEVEL meter.
- **TILT** — A on/off, E low shelf, H high shelf (64 = flat).
- **CRUSH** — A on/off, D mode (BITS/**REDUX**/CRUNCH), E amount, F tune, LEVEL meter.
- **PITCH** — A on/off, D mode (WOB/SHFT), E speed, F depth, G mix.
- **STEREO** — A on/off, D mode (FLAN/PAN/WIDE), E speed, F depth, G mix, H feedback.
- **DELAYS** — A on/off, D mode (WRMZ/GRAINZ), B/C/E/F/G/H the active mode's six
  params; true bypass off; mono wet.
- **PERFORM** — static page, A–H one depth per engine; the 16 trigs are
  momentary performance pads.
- **WASH / RADIO / DESTROY / SPACE** — one-slider macros. **WASH** = WOB only
  (75 % depth / 30 % rate) + the WRMZ delay's MIX/FB; **RADIO** = EQ tilt (low →
  0, high → 127) + TRSH fold + SRR-only crush; **DESTROY** = fold + bits + ring;
  **SPACE** = WAVE stereo width. Capture/restore is per engine, so CRUSH/REDUX is
  not tied to WASH.

Every parameter is **0–127** and moves one step per notch, the stock convention
(EQ LOW/HIGH show 0–127 with 64 = flat). The FX also respond to **incoming MIDI
CC**; see [`docs/MIDI-CC.md`](docs/MIDI-CC.md).

## Pages

Twelve master pages (**FUNC + LFO**; **LEFT/RIGHT** rotates; **UP** opens the
macro tree). Each FX page has a frameless animated graphic that collapses at
neutral; PERFORM is static; the macros each show one slider + a graphic.
Per-pattern settings are packed into **one reserved MIDI track** (t=7,
`pattern+0x1BB0`, `"DGX4"`, CH 16) and save/reload with the pattern; see
[`docs/PATTERN-STORAGE.md`](docs/PATTERN-STORAGE.md).

| RING | FOLD | TILT |
|---|---|---|
| ![RING](docs/img/ui-ring.png) | ![FOLD](docs/img/ui-fold.png) | ![TILT](docs/img/ui-tilt.png) |

| CRUSH | PITCH | STEREO | PERFORM |
|---|---|---|---|
| ![CRUSH](docs/img/ui-crush.png) | ![PITCH](docs/img/ui-pitch.png) | ![STEREO](docs/img/ui-stereo.png) | ![PERFORM](docs/img/ui-perform.png) |

## CPU footprint

Everything runs on the Digitone's **main CPU (Core A)**; the FM DSP (Core B) is
untouched. A bypassed section costs ~0. The DELAYS line is the largest single
cost (mono s16, `WZ_N=2^14`); the 4.0 line runs its per-frame gains on the
**eMAC** (`src/emac.h`) and uses s16 wave lines. WASH uses a static WRMZ read
(`MOD=0`) and skips the DC blocker while on.

| build | `.run` | `.bss` | notes |
|---|---|---|---|
| Digitone 4.0c | 25,594 | 47,182 | 11 sites, 970 relocs, `imports nothing` |
| Digitakt 4.0c | 23,096 | 51,232 | 4 sites, 931 relocs, `imports nothing` |

Full ledger: [`docs/OPTIMIZATION-ROUND.md`](docs/OPTIMIZATION-ROUND.md)
(historical `docs/OPTIMIZATION.md`, `PERF-OPT-PLAN.md`).
**Output ceiling:** a final soft limiter keeps the mix below 24-bit full scale
(transparent below ~-2.5 dBFS, asymptotic max ~-0.7 dBFS).

## Layout

```
src/            corea.h, buffx.h, emac.h, sin256.h (shared helpers)
mods/<id>/      mod.json + sources
mods/tonefx/    the merged 4.0c suite (format 2; requires the core, no core inside)
docs/           pattern storage, MIDI CC, the CPU ledger, plans
releases/       older RingTone snapshots (current releases live in Tone+FX)
LICENSE         GPL-2.0
```

## Getting it

elekloader builds a custom OS **on your machine** from your own stock
`Digitone_and_Digitone_Keys_OS1.43.syx` plus these mods; it never distributes
firmware. **New releases live in
[Tone+FX](https://github.com/DigiAlchemydsp/Tone-FX/releases).**

## Building from source

The suite ships as one merged mod, `mods/tonefx/` (it requires the core, which it
does not include). **One source builds both OS versions**; the stock file picks
the release (`ports.1.44` in `mods/tonefx/mod.json`). `--version` must be exactly
4 ASCII characters.

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "<elekloader checkout>"

# OS 1.43 -> out/tonefx-4.0c.elemod
python -m elekloader.sdk.build "mods\tonefx" --stock Digitone_and_Digitone_Keys_OS1.43.syx
python -m elekloader.patch --stock Digitone_and_Digitone_Keys_OS1.43.syx `
  --mod core-dn1-4.0.elemod `
  --mod mods\tonefx\out\tonefx-4.0c.elemod --out ToneFX-1.43.syx --version 4.0c

# OS 1.44 -> out/tonefx-4.0c-os1.44.elemod
python -m elekloader.sdk.build "mods\tonefx" --stock Digitone_and_Digitone_Keys_OS1.44.syx
python -m elekloader.patch --stock Digitone_and_Digitone_Keys_OS1.44.syx `
  --mod core-dn1-4.0-os1.44.elemod `
  --mod mods\tonefx\out\tonefx-4.0c-os1.44.elemod --out ToneFX-1.44.syx --version 4.0c
```

The components (`digimeter`, `digieq`, `digiring`, `digifold`, `digicrush`,
`digiwave`, `digiwrmz`) can still be built and combined individually.

## Status

Current source: **Tone+FX 4.0c** (twelve pages incl. DELAYS; PERFORM + the four
macros; per-pattern store `"DGX4"`; MIDI CC). The 4.0c Digitone build is
**byte-identical** to the published `Tone+FX` v4.0c elemods. Verified in
**digiemu** (boot/settle, `dsp_running=2`, all pages, the store round-trip, the
macro values, 0 faults). See `HANDOFF.md` for state and open items.

## Testing

```powershell
python tests/digiemu_pattern_store.py --fw <dn1-...> --map <syx.map.json>   # store regression
python tests/digiemu_nav.py --fw <dn1-...>                                  # page navigation
python tests/digiemu_midi_cc.py --fw <dn1-...> --map <syx.map.json>         # MIDI CC hook
python tests/_timing_buffx.py --fw <dn1-...> --map <syx.map.json> --ms 120  # CPU margin
python tests/_timing_wave.py  --fw <dn1-...> --map <syx.map.json> --ms 120  # wave modes
python tests/_probe_mix.py --fw <dn1-...> --map <syx.map.json>              # WOB/SHFT/FLAN/WIDE
```

(The `digiemu_*` tests need the patched-Unicorn venv; `--fw` is a firmware the
app built from `core-dn1` + the mods.)

## Parked / future work

- **WASH delay CPU:** half-rate WRMZ wet, mono WOB, or a delay-time cap (audible
  trades); then 4-accumulator MAC interleaving and eMAC on `fold`/`crush` Q8.
- **Sequencer p-lock automation** for the FX params (branch `tonefx-plock`).
- **Per-voice filter rewrite + digimachine** (branch `filter-and-digimachine`).
- **LFO destinations** / **audio-chain reroute** (`docs/MODULATION-AND-ROUTING.md`).
- **FAST AUDIO on the DN** (`docs/FAST-AUDIO-DN.md`).

## Licence

Our own code and docs: **GPL-2.0-or-later** ([LICENSE](LICENSE)). This does not
cover the manufacturer's firmware, which is never distributed here.
