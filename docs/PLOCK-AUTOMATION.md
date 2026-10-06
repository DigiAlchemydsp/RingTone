# Sequencer automation (p-locks) for the Tone+FX params — findings + plan

Status: **implemented on branch `tonefx-plock` (tonefx 2.3d), verified in
digiemu.** OS 1.43. Goal: let the four internal (synth) tracks' sequencer
**record** Tone+FX parameter changes as parameter locks and **play them back**,
so the master FX are automated per step like stock parameters.

## Implemented (raw bridge; verified in digiemu)

- Five params are automated for now, on **spare lock ids 60..64** (the stock slot
  table `0x4018FE98` only maps ids 0..59 and 73..76): ring depth, ring rate, fold
  amount, EQ low, EQ high.
- **Record:** on the DIGI FX / FOLD-EQ pages, hold a **trig key** and turn the
  matching encoder; `digictl` writes the value into that step's lock word.
  Verified: lock `id60` goes `0xFFFF` -> `54`.
- **Playback:** `digictl_tick` reads the current step (`0x4138E1C8`) and, for
  each reserved id, the first non-`0xFFFF` lock across the four tracks, then
  drives the FX global. Verified: poke `id60 = 42` -> `digiring_depth = 42`.

## Hardware findings and the fix (2.3d)

The unit showed: automation works but **the trig does not light yellow**,
**CLEAR SEQUENCE does not remove it**, and it **only fires ~1/4 of the time**.

The stock p-lock accessors were then located (all in the `0x40023xxx` block):

| addr | what |
|---|---|
| `0x40023CC0` | has-lock(track, step, id) |
| `0x40023D22` | get-lock(track, step, id) |
| `0x40023DD4` | count locks in a track |
| `0x40023ED2` | recount **one step's** locks into its count word |
| `0x40023FAA` | rebuild the **per-id presence flags** for a track |
| `0x40024052` | remove one lock (writes `0xFFFF`, then recounts) |
| `0x40024124` | clear all locks on a step |

So a locked step keeps **three** things, and writing only the value word missed
two:

1. the **lock value** at `base + step*0xA0 + id*2` (`base = pattern + 0x1E80 +
   track*0x284F`); `0xFFFF` = unlocked;
2. the **per-step lock count** at `base + step*0xA0 + 158` (word 79 of the 80-word
   step block) — the display reads this to draw the **yellow trig**;
3. the **per-id presence flag** at `base + 0x2800 + id` (byte; the `0x4F` = 79
   bytes at the end of the `0x284F` stride) — 1 if that id is locked anywhere on
   the track.

`digictl` now writes all three: after the value word it recounts the step into
`+158` and sets the presence byte (`dn_plock_fixup`), mirroring `0x40023ED2` /
`0x40023FAA`. Verified in digiemu: the step count goes `0 -> 1` and the presence
flag `0 -> 1` alongside the value. This is what drives the yellow trig and lets
CLEAR find and remove the locks.

## Still open: the step/page index (~1/4)

The 16 trig keys are the **current pattern page's** steps; our record always
writes steps 0..15 (page 1), while the playback reader uses the global 0..63 step
(`0x4138E1C8`) — so it only lines up on one of the four pages. The active-page
global was not found (PAGE/trig presses only changed UI redraw bytes in the
scanned RAM). Next: find the page state (or read it from the same context the
stock add-lock uses), then map the held trig to `page*16 + trig`.

## Longer term

Adding our params to the stock **parameter table** would make them real, lockable
parameters so the whole stock UI/sequencer/LFO/display stack handles them
natively (no raw writes at all).

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
