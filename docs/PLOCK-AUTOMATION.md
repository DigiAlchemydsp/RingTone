# Sequencer automation (p-locks) for the Tone+FX params — findings + plan

Status: **implemented on branch `tonefx-plock` (tonefx 2.3d), verified in
digiemu.** OS 1.43. Goal: let the four internal (synth) tracks' sequencer
**record** Tone+FX parameter changes as parameter locks and **play them back**,
so the master FX are automated per step like stock parameters.

## Implemented (verified in digiemu `dn1-2.3d-905bf82e`)

- Five params are automated for now, on **spare lock ids 60..64** (the stock slot
  table `0x4018FE98` only maps ids 0..59 and 73..76, so the stock engine ignores
  these): ring depth, ring rate, fold amount, EQ low, EQ high.
- **Record:** on the DIGI FX / FOLD-EQ pages, hold a **trig key** (1..16) and
  turn the matching encoder; `digictl` writes the value into that step's lock
  word for the reserved id. Verified: hold trig 1, turn RING depth -> the lock
  word `id60` goes `0xFFFF` -> `54`.
- **Playback:** `digictl_tick` reads the current step (`0x4138E1C8`) and, for
  each reserved id, the first non-`0xFFFF` lock across the four tracks, then
  drives the FX global. Verified: poking `id60 = 42` -> `digiring_depth = 42`;
  `id60 = 99` -> `99`.
- The track is the last `T1..T4` pressed (tracked in `digictl_key`); no active
  track global was found, so we track it ourselves.

### Caveats / next

- Playback runs at the **UI tick** rate (`digictl_tick`), not the audio block
  rate: the render events (`ev_render_in/out`) did not fire in the idle emulator,
  and a p-lock only changes at a step boundary, so tick rate is ample.
- The record gesture uses trig 1..16 = steps 1..16 (pattern page 1); the other
  three pattern pages are not wired yet.
- Only 5 of the params are bridged; ring on/off, fold on/off and EQ on/off are
  toggles and can be added the same way.
- The per-pattern store still holds the base (non-automated) value; a lock
  overrides it for that step. The store was bumped to v3 in 2.3c.
- Needs a **hardware pass** (record a lock, play, confirm the FX follow, and that
  the stock engine is untouched on the spare ids).

## Why it does not work today

The Tone+FX params are plain C globals in the mods' `.bss`. The sequencer only
knows the **79 stock lock ids** (one per sound parameter slot); it has no idea
our globals exist, and the MIDI CCs we use (`8/11/36/37/40/67/68/69/96`) are
deliberately ones the stock CC router (`0x400ED94E`) ignores. So neither the
knob-record path nor the CC path can capture them.

## The stock p-lock machinery (measured)

**Storage** (confirmed via the `plock2sound` mod, which reads it, and the
clear/init code at `0x400152A0` / `0x40015180`):

```
locks(track, step) = pattern + 0x1E80 + track*0x284F + step*0xA0
```

- `pattern = *(0x4138E214)`, `track = 0..3` (synth tracks), `step = 0..63`.
- 80 `int16` per step (79 lock ids used, plus a word at `+158`);
  `0xFFFF` = **no lock**, `0` is a valid lock.
- A per-step "has locks" byte sits at `trackbase + 0x2800`.

**Apply** — the conversion at `0x400090F2` folds the lock words into the live
per-track value array the engine reads (`0x80001502 + 106*v + 2*slot`); it walks
all 79 ids (loop bound 79 at `0x40009188`) using the id→slot table at
`0x4018FE98` (4-byte entries, value in byte 3).

**Sequencer tick** — `0x40093780`: walks the four tracks (`+0x3D0` each), and the
play position counter is **`0x4138E1C8`** (word, incremented at `0x400937F2` and
wrapped against the pattern length `0x41367D10`). A second byte counter
`0x4138E20C` advances alongside it.

**Panel map** (`devices/digitone.toml`): `T1..T4` = codes `42..45`, trigs 1..16 =
`26..41`, `RECORD` = 10, `PLAY` = 11, `STOP` = 12.

## Proposed bridge (self-contained, no stock UI change)

Record and playback can both be done inside `digictl` using the storage above.

1. **Reserve spare lock ids.** Pick a few ids the stock engine never locks
   (the DN has ~53 live slots per voice vs 79 ids, so high ids are candidates).
   One id per Tone+FX param (ring depth/rate, fold, EQ low/high). *To confirm:*
   which ids are truly spare (write one, play, check the stock sound is
   unchanged).

2. **Record** (`digictl_enc`, on the DIGI pages): track the last `T1..T4`
   pressed and the held trigs in `digictl_key` (no active-track global needed —
   we track it ourselves). When an encoder moves while a trig is held, also
   write the value into that step's lock word for the reserved id:
   `pattern + 0x1E80 + track*0x284F + step*0xA0 + id*2`.

3. **Playback** (`digictl_mod_in`, an existing per-block `ev_render_in` reader):
   read the current step `0x4138E1C8`, scan the four tracks' lock words for each
   reserved id (only our ids are non-`0xFFFF`), and drive the Tone+FX global.
   This needs no active-track global either.

4. The per-pattern store keeps the non-automated base value; a lock overrides it
   for that step, exactly like a stock p-lock.

## Open items before it can ship

- **Verify the play position** `0x4138E1C8` is the *playing* step (the emulator
  snapshot is an empty pattern, so playback does not advance — needs a populated
  pattern).
- **Pick genuinely spare ids** (see above) and confirm the stock apply leaves
  them harmless.
- Decide the record gesture (held trig + encoder) and whether to also expose it
  via MIDI CC.
- Test matrix: lock on each track/step, unlock (`0xFFFF`), zero lock, pattern
  switch/reload (the store already round-trips the base value).

## Notes

- The lock region (`pattern + 0x1E80`) does not collide with the per-pattern
  store (`pattern + 0x1040`, 64 bytes) or the pattern struct's other fields.
- `plock2sound` proves a mod can read this region safely; this bridge writes it,
  so the record path must respect the stock `0xFFFF`/valid-zero convention and
  the per-step "has locks" byte.
