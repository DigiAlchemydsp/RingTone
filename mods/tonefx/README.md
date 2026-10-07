# tonefx — the Tone+FX suite as one elemod

This mod is a **merge** of the five suite mods:

- `../digimeter/meter.c`
- `../digieq/eq.c`
- `../digiring/ring.c`
- `../digifold/fold.c`
- `../digictl/` (`digictl.c`, `cc_glue.s`)

`mod.json` pulls in all their sources, sites and subscriptions and declares
`requires: ["core"]`. It is **format 2**: it does **not** include the core, so
it combines with `core-dn1-2.0a.elemod` and any other elekloader mods.

```powershell
python -m elekloader.sdk.build . --stock Digitone_and_Digitone_Keys_OS1.43.syx
python -m elekloader.patch --stock <stock> --mod <core-dn1-2.0a.elemod> `
  --mod out/tonefx-3.0.elemod --out ToneFX.syx --version 3.0a
```

The five component mods stay the source of truth; if their code changes, rebuild
`tonefx` too (and keep the CC-router site `op: "jmp"` in sync with
`../digictl/mod.json`). Do **not** use `elekloader.mkmod` for the release: that
produces a format-1 whole build (with the core), which cannot be combined with
other mods. See `../../docs/MIDI-CC.md`.
