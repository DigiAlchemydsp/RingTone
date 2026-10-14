# Tone+FX — how to execute the optimization plan

Companion to `docs/PERF-OPT-PLAN.md` (the list) and `docs/OPTIMIZATION.md` (the
ledger). Work one item at a time; measure; commit; record.

## 0. Setup

```powershell
$env:PATH="C:\SysGCC\m68k-elf\bin;"+$env:PATH; $env:ELEKLOADER_CROSS="m68k-elf-"
$env:PYTHONPATH="C:\Users\benan\Music\ELEKTRON\00 ELEKLOADER NEW\elekloader-main"
$stock="C:\Users\benan\Music\ELEKTRON\Digitone_and_Digitone_Keys_OS1.43.syx"
$py="C:\Users\benan\AppData\Local\Temp\opencode\digiemu-venv\Scripts\python.exe"
```

You are in the **perf-opt** worktree (`digitone_corea_perf`). The main worktree
is `../digitone_corea` (its `HANDOFF.md` is gitignored — read it there).

## 1. Per-item workflow

1. **Branch/commit hygiene:** one item = one commit, message `perf: <item>`.
   Never mix two optimizations in a commit (you cannot attribute the win).
2. **Implement** per `PERF-OPT-PLAN.md`, keeping the hard constraints in
   `AGENTS.md` (no libc/FPU, 32-bit, subscription-only, `imports nothing`).
3. **Build:** `python -m elekloader.sdk.build "mods\tonefx" --stock $stock`.
   Record `.run`, `.bss`, sites, relocs — **must say `imports nothing`**.
4. **Patch** a test `.syx` (bump the version tag, e.g. `3.5d` → `3.5d-p1`) so
   the emulator picks a fresh firmware dir.
5. **Regress** (headless, fast): `digiemu_pattern_store.py`,
   `digiemu_midi_cc.py --map testout\<ver>.syx.map.json`, `_diag_perf.py`,
   `_diag_macros.py`, `_diag_wavesplit.py`, `_diag_macro_store.py`. Then the
   relevant **live** test (`_diag_perf_live.py` / `_diag_wash_live.py` /
   `_diag_radio_live.py`).
6. **Measure** (§Measuring). 7. **Record** (§Recording). 8. **Commit.**

## 2. Measuring

**Static footprint** (every item): the build line (`imports nothing`, `.run`,
`.bss`, relocs). Cross-check the elemod section sizes.

**Render timing** (items 2, 7, 8, 9, 10, 11, 12, 15): the cheap bounded pass is
a settled `gui.snap` + `emu.cftiming` (the render-vector worst / p99 cycles and
the **deadline margin**), per `HANDOFF.md` §5. The full
`python -m emu.portable --check <syx> --timing` is slow (all 5 stages) — use it
only to confirm a big win. Compare **off vs on** and **each page**:
- FX off, all FX on, and the heaviest mode (SHFT / FLAN) — before vs after.

**UI draw cost** (items 1, 3, 4): add a temporary `static unsigned dn_calls;`
incremented in the page draw (or count `DN_FILLRECT`), read it via the map after
a fixed number of ticks; or just count calls per page from the source. Expect
#1 to drop a page from dozens–hundreds to a handful.

**Audio A/B** (items 2, 7, 8, 9, 10, 12): for a pure refactor (#2, #7) require
**bit-identical** output on the factory pattern — capture the SSI buffer in
digiemu and diff. For a deliberate trade (#9/#10/#12) capture before/after and
report the audible delta honestly (lo-fi only).

**Emulator flakiness:** the second CPU sometimes throws
`access violation reading 0x10` and freezes the render mid-test. Re-run; keep
live sessions short; don't attribute a freeze to your change without a re-run.

## 3. Recording

For each landed item append to `docs/OPTIMIZATION.md`:
- the method (one line) and its section (§4/§8),
- `.run`/`.bss` before→after,
- the timing delta if measured (worst/p99, deadline margin),
and update `docs/PERF-OPT-PLAN.md`'s table **Status** column. Note anything
still unverified in `HANDOFF.md`.

## 4. Suggested order

1. **#1 direct framebuffer** → **#3 partial clear** → **#4 meter gate** →
   **#8 ring block-rate** → **#10 cheap blend** → **#6 cache `dn_out_off`** →
   **#14 store gating** (all safe, additive).
2. **#2 fuse the passes** (big, one commit; A/B bit-exact).
3. **#7 EMAC** (big; A/B bit-exact).
4. **#9 SHFT trim**, **#11 hoist branches**, **#15 flags/unroll/align**.
5. **#12 delay line** — land with the flanger flush/prime work (HANDOFF §6).
6. **#13 `.fast` SRAM** only if the device profile changes.

## 5. Definition of done (per item)

- Builds clean, **`imports nothing`**; regression set passes.
- Audio unchanged (or the trade is stated and confined to lo-fi modes).
- The win is **measured**, not assumed; numbers recorded in `OPTIMIZATION.md`.
- One `perf:` commit; `PERF-OPT-PLAN.md` status updated.
- If it regresses anything, `git revert` it and note why in the plan.

## 6. Landing to main

When the branch is clean and each item is measured, open a PR from `perf-opt`
into `main` (or cherry-pick the `perf:` commits). Do **not** push `perf-opt`
work to `main` mid-experiment. The release repo (`Tone+FX`) is cut separately
from `main` only.
