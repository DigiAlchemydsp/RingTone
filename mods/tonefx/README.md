# tonefx — the merged Tone+FX suite (4.0c)

One elemod for the whole Digitone suite: `digiwave`, `digiring`, `digieq`,
`digifold`, `digicrush`, `digimeter`, `digiwrmz` (DELAYS) and `digictl` (pages,
store, CC, macros), plus the TONE+FX boot splash. It **requires** the core
(`core-dn1` 4.0) and does not include it.

- Permanent chain: `ring → EQ → crush → fold → PITCH → DELAYS → STEREO →
  ceiling → meter`. The WAVE insert is split into `digiwave_pitch_render_out`
  (61) and `digiwave_stereo_render_out` (63), with `digiwrmz_render_out` at 62.
- Per-pattern store: all 51 params packed into MIDI track 4
  (`pattern+0x1BB0`, `"DGX4"`, CH 16). See `../../docs/PATTERN-STORAGE.md`.
- Macros: WASH (WOB 75 %/30 % + WRMZ mix/fb), RADIO (EQ tilt + TRSH + SRR),
  DESTROY, SPACE. Per-engine capture/restore.
- Build (from the repo root): `python -m elekloader.sdk.build mods\tonefx
  --stock <stock>`. One source builds 1.43 and 1.44 (`ports.1.44`).
  `--version 4.0c`.

`render.c` and `splash.s` are the suite's boot splash / render glue, shared by
the merged build. The modules can still be built individually.
