# Building & testing — Tone+FX (Digitone source, 4.0c)

This tree is the Digitone build source. It builds `mods/tonefx` (the suite
+ DELAYS). The Digitakt port builds from
`Tone+FX/DIGITAKT PORT/digi1_mods-main/mods/tonefx`.

## Environment (once per shell)

```powershell
$env:PATH="C:\SysGCC\m68k-elf\bin;"+$env:PATH
$env:ELEKLOADER_CROSS="m68k-elf-"
$env:PYTHONPATH="C:\Users\benan\Music\ELEKTRON\00 ELEKLOADER NEW\elekloader-main"
$E="C:\Users\benan\Music\ELEKTRON\00 ELEKLOADER NEW\elekloader-main\build\windows\bundled"
$s143="C:\Users\benan\Music\ELEKTRON\Digitone_and_Digitone_Keys_OS1.43.syx"
$s144="C:\Users\benan\Music\ELEKTRON\Digitone_and_Digitone_Keys_OS1.44.syx"
```

## Build · lint · patch (OS 1.43; repeat with `$s144`)

```powershell
python -m elekloader.sdk.build mods\tonefx --stock $s143
# -> mods\tonefx\out\tonefx-4.0c.elemod

python -m elekloader.lint mods\tonefx\out\tonefx-4.0c.elemod `
  --stock $s143 --with "$E\core-dn1-4.0.elemod"

python -m elekloader.patch --stock $s143 --mod "$E\core-dn1-4.0.elemod" `
  --mod mods\tonefx\out\tonefx-4.0c.elemod `
  --out testout\exp-1.43.syx --version 4.0c
```

- `--version` must be exactly 4 ASCII characters.
- The patch writes `<out>.syx.map.json` next to the syx (symbol map for tests).
- 1.44: build with `$s144`, patch with `$E\core-dn1-4.0-os1.44.elemod`.

## Emulator (digiemu)

```powershell
$env:PYTHONPATH="C:\Users\benan\Music\ELEKTRON\digiemu-main"
python -m emu.portable --add testout\exp-1.43.syx --yes   # -> dn1-4.0c-<sha8>
```

Then, with the fw dir name and the map json:

```powershell
$env:DIGIEMU="C:\Users\benan\Music\ELEKTRON\digiemu-main"
python tests\digiemu_pattern_store.py --fw dn1-4.0c-<sha8> --map testout\exp-1.43.syx.map.json
python tests\_timing_buffx.py --fw <fw> --map <map> --ms 120
python tests\_diag_buffx_live.py --fw <fw> --map <map>
python tests\_probe_mix.py --fw <fw> --map <map>
```

`digiemu_pattern_store.py` is the store regression (old blocks clean, `"DGX4"`
at `+0x1BB0`, per-pattern isolation/reload).

## Verification checklist (4.0c)

| check | expected |
|---|---|
| build (DN 1.43/1.44, DT 1.53/1.54) | `imports nothing`; `.run 25,594 / .bss 47,182` (DN), `23,096 / 51,232` (DT) |
| lint | `links as core 4.0 > tonefx 4.0c`; RAM within budget |
| patch | byte-exact against each stock file |
| chain (DN `mod.json`) | `digiwave_pitch_render_out` 61 → `digiwrmz_render_out` 62 → `digiwave_stereo_render_out` 63 |
| chain (DT `master.c`) | pitch → wrmz → stereo, same order |
| store | digiemu store test PASS |
| macros | WASH 95/38 + WRMZ 96/64 + DC skip; RADIO 0/127 + SRR 40 |

The historical 0.x buffer-FX footprint ledger (Tailz/Grainz rounds) is in
`docs/OPTIMIZATION-ROUND.md` §1–§12; the current state is in `HANDOFF.md`.
