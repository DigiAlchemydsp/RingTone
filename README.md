# Digi FX — Digitone mk1

Unofficial, community-made [elekloader](https://github.com/irpina/elekloader)
mods for the **Elektron Digitone mk1 / Digitone Keys, OS 1.43**: three
master-insert effects, output metering, and a **DIGI FX page on the master page
tree (FUNC+LFO)** that controls them.

> Unofficial and unsupported. Not affiliated with, endorsed by or supported by
> Elektron. Flashing modified firmware is at your own risk. Read
> [`releases/README.md`](releases/README.md) and [`HANDOFF.md`](HANDOFF.md) first.

## Mods

| mod | what |
|---|---|
| `digimeter` | output level metering (log L/R bars), drawn on the DIGI FX page |
| `digieq` | master tone tilt (low/high gain) |
| `digiring` | master ring modulator / tremolo |
| `digifold` | master wavefolder (triangle fold), on/off + amount |
| `digictl` | the DIGI FX master page that edits the three + the meter |

The master mix runs **ring → EQ → fold**.

## Layout

```
src/            corea.h, sin256.h  (shared helpers)
mods/<id>/      mod.json + sources + out/<id>-<ver>.elemod
releases/       the packaged .elemods + a README (no firmware)
DSP.md          DSP reference (addresses, the two CPUs, the FM engine, ...)
HANDOFF.md      session state and the open item (per-pattern persistence)
LICENSE         GPL-2.0
```

## Getting it

elekloader builds a custom OS **on your machine** from your own stock
`Digitone_and_Digitone_Keys_OS1.43.syx` plus these mods; it never distributes
firmware. Take the `.elemod`s from [`releases/`](releases/) (plus
`core-dn1-2.0a.elemod`), add them in elekloader's window, and build the `.syx`.
See [`releases/README.md`](releases/README.md) for install and recovery.

## Building from source

```powershell
$env:PATH = "C:\SysGCC\m68k-elf\bin;" + $env:PATH
$env:ELEKLOADER_CROSS = "m68k-elf-"
$env:PYTHONPATH = "<elekloader checkout>"
$stock = "<your> Digitone_and_Digitone_Keys_OS1.43.syx"
$core  = "core-dn1-2.0a.elemod"
foreach ($m in 'digimeter','digieq','digiring','digifold','digictl') {
  python -m elekloader.sdk.build "mods\$m" --stock $stock
}
python -m elekloader.patch --stock $stock --mod $core `
  --mod mods\digimeter\out\digimeter-1.1.elemod --mod mods\digieq\out\digieq-1.0.elemod `
  --mod mods\digiring\out\digiring-1.0.elemod --mod mods\digifold\out\digifold-1.0.elemod `
  --mod mods\digictl\out\digictl-1.2.elemod --out custom.syx --version 2.0o
```

## Status

Tested in the **digiemu** emulator (boots, settles, `dsp_running=2`; the page
draws as the fourth master entry). **Not yet tested on hardware.** Settings are
**not saved per pattern yet** — see [`HANDOFF.md`](HANDOFF.md) §6.

## Licence

Our own code and docs: **GPL-2.0-or-later** ([LICENSE](LICENSE)). This does not
cover the manufacturer's firmware, which is never distributed here.
