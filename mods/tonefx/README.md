# tonefx — the Tone+FX suite as one elemod

This mod is a **merge** of the suite mods:

- `../digimeter/meter.c`
- `../digieq/eq.c`
- `../digiring/ring.c`
- `../digifold/fold.c`
- `../digicrush/crush.c`   (Crunch / Redux: BITS / SR / CRUNCH)
- `../digiwave/wave.c`     (WOB / SHFT / FLAN / PAN / WIDE modulation)
- `../digictl/` (`digictl.c`, `cc_glue.s`)

`mod.json` pulls in all their sources, sites and subscriptions and declares
`requires: ["core"]`. It is **format 2**: it does **not** include the core, so
it combines with `core-dn1-4.0.elemod` and any other elekloader mods.

**One source builds for both OS versions.** The stock file picks the release:
1.43 uses the top level (the `#ifndef *_ADDR` defaults in the C sources and the
`defsym` symbols in `cc_glue.s`/`splash.s`); 1.44 uses `ports.1.44` in
`mod.json`, which replaces `defsym`, `cflags` and `sites` with the 1.44 values.
`--version` must be **exactly 4 ASCII characters**.

```powershell
# OS 1.43 -> out/tonefx-<ver>.elemod
python -m elekloader.sdk.build . --stock Digitone_and_Digitone_Keys_OS1.43.syx
python -m elekloader.patch --stock <stock143> --mod <core-dn1-4.0.elemod> `
  --mod out/tonefx-3.5r.elemod --out ToneFX-1.43.syx --version 3.5r

# OS 1.44 -> out/tonefx-<ver>-os1.44.elemod
python -m elekloader.sdk.build . --stock Digitone_OS1.44.syx
python -m elekloader.patch --stock <stock144> --mod <core-dn1-4.0-os1.44.elemod> `
  --mod out/tonefx-3.5r-os1.44.elemod --out ToneFX-1.44.syx --version 3.5r
```

To add an address to a future port: keep the 1.43 value as the `#ifndef` default
in the C source and add the 1.44 value as `-D…_ADDR=…` in `ports.1.44.cflags`
(or a `defsym` symbol in the asm). The current 1.44 values are in
`mod.json` → `ports.1.44`.

The five component mods stay the source of truth; if their code changes, rebuild
`tonefx` too (and keep the CC-router site `op: "jmp"` in sync with
`../digictl/mod.json`). Do **not** use `elekloader.mkmod` for the release: that
produces a format-1 whole build (with the core), which cannot be combined with
other mods. See `../../docs/MIDI-CC.md`.
