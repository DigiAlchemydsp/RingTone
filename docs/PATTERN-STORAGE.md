# Per-pattern storage for the DIGI FX params (Digitone mk1)

Status: **implemented (digictl 2.9), verified in digiemu.** The FX parameters
save and reload with the pattern, like stock parameters, in **one reserved
MIDI track** (channel 16). MIDI tracks 1-3 (channels 1-15) and the synth tracks
are never touched.

## Why not the old blocks (channels 1-3)

`digictl` 2.0-2.8 wrote its settings into the pattern struct's MIDI-track blocks
at `pattern + 0x1040 / +0x1410` — `track_t + 0x100` of MIDI tracks 1 and 2. They
measured zero on *unconfigured* tracks, but a **configured** MIDI track writes
its channel/page there, so the stock data and our values corrupted each other
(jumping FX values, moved MIDI channels). Spreading the store over several
tracks also meant several tracks could be hit.

## The reserved block (MIDI track 4, channel 16)

All params now live in **one** MIDI track's 64-byte block:

```
track_t = 0x3D0; MIDI track 4 (t = 7) -> pattern + 7*0x3D0 + 0x100 = pattern + 0x1BB0
```

Reserve that track on **MIDI channel 16** and leave it alone. The store writes
only `pattern + 0x1BB0`; the other three MIDI-track blocks and every synth track
are untouched, so channels 1-15 are unaffected.

Because 35 params do not fit as `int16` in 64 bytes, they are **packed**:

```
+0..3   "DGX4" magic
+4      version (1)
+5..6   count (35)
+7..    bitstream, little-endian, 1-7 bits per param in DN_STORE order
```

The bit widths are in `dn_stbits` (`1` for every on/off/switch, `7` for 0..127,
`3`/`4` for the parked LFO bridge). 166 bits -> 21 bytes + the 7-byte header =
28 of the block's 64 bytes; the tail is cleared.

## The sync and the guard

`ev_tick` (one UI frame) runs `dn_store_sync()`:

- **new pattern pointer** (switch / first sync): a block carrying the `"DGX4"`
  magic is loaded into the globals; a block without it (a fresh pattern) adopts
  the live values, so the sound never jumps;
- **a page edit** (`dn_store_dirty`, set by every encoder / key / CC branch):
  write the globals into the block;
- **the block changed behind us**: adopt it only if the magic is still there (a
  genuine pattern reload). If it is gone, a stock write landed in the block —
  reclaim it from the live values instead of reading it.

The other three MIDI blocks (`+0x1040`, `+0x1410`, `+0x17E0`) carry no magic in
a new build and are never read or written; `tests/digiemu_pattern_store.py`
checks they stay clean.

## The PERFORM page momentary pads

Unchanged. The 16 trig pads (`pf_apply` in `digictl.c`) override a block's depth
only while the pad is held (and the short release ramp), restoring the saved
value afterwards. They **never set `dn_store_dirty`** and never write the block,
so the pattern value is always the resting position. Pad state lives in plain
`.bss` (`pf_*`).

## Verified in digiemu

`dn1-4.0a` (core-dn1 4.0 + the suite, digictl 2.9): `tests/digiemu_pattern_store.py`
PASS — `+0x1040/+0x1410/+0x17E0` carry no magic and stay clean; `+0x1BB0` carries
`"DGX4"`; an edit is saved; a value set on one pattern does not leak to another;
a return reloads it.
