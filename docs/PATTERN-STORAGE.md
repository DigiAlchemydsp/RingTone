# Per-pattern storage for the DIGI FX params (Digitone mk1, OS 1.43)

Status: **implemented (digictl; current 1.9, shipped in the merged `tonefx`
mod), verified in digiemu.** The FX parameters save and reload with the pattern,
like stock parameters, instead of living only in the mod's `.bss`.

## The problem

The DIGI FX / FOLD-EQ parameters (`digiring_*`, `digieq_*`, `digifold_*`,
`digimeter_on`, `digimod_*`) are C globals in the mods' `.bss` (RAM
`0x47BE0000-0x47C00000`). That region is cleared at boot, so the settings were
lost at power-off and did not change with the pattern.

## The pattern store (measured)

The project's patterns are an array of `0x1611D`-byte storage structs:

```
pattern(slot) = 0x407FC414 + slot * 0x1611D        (slot 0..127)
current pattern pointer: *(0x4138E214)
```

Confirmed from the pattern dispatcher `0x40094EF4` (it stores its argument at
`0x4138E214`) and the manager code at `0x400FE03A`, which computes
`0x407FC414 + index*0x1611D`. `*0x4138E214` moved by exactly `0x1611D` on a
pattern switch (measured in digiemu). The struct is `patternStorage_v11_t`
(RTTI); the render's algorithm getter `0x4009444A` reads its last long at
`+0x16119`. The OS copies the struct wholesale (several
`movel #90397,%sp@-` memcpy/memset sites, e.g. `0x400157F0`).

## The reserved block

Each `track_t` record is `0x3D0` bytes (8 tracks: 4 synth at `t=0..3`, 4 MIDI
at `t=4..7`). Every track has a 64-byte area at `track_t + 0x100`:

- **synth tracks** use it (voice/sound data — nonzero);
- **MIDI tracks** leave it **zero in all 128 slots** (measured) and the OS's
  parameter mirror never writes it: poking a marker there survived a FILTER
  knob edit (which runs the live→storage mirror).

So `pattern + 0x1040` (MIDI track 0's block) is a safe, saved, 64-byte scratch
per pattern.

## The layout

`digictl` keeps 12 parameters there:

```
+0..3   "DGX1" magic
+4..5   version (3: the params are 0..127)
+6..7   count (12)
+8..   12 x int16, big-endian, in DN_STORE order
```

The 12 params are ring (on, depth, rate), EQ (low on, high on, low, high),
fold (on, amount), meter (on) and the LFO bridge (dest, voice). Version 3
dropped the earlier per-voice-filter params; an older block (version 2) fails
the magic check and is treated as a fresh pattern, so it starts from the live
values.

`ev_tick` (one UI frame) runs `dn_store_sync()`:

- **new pattern pointer** (switch / first sync): if the magic is present, load
  the block into the globals; otherwise write the globals (a fresh pattern
  adopts the live values);
- **a page edit** (`dn_store_dirty`, set by every encoder/key branch): write the
  globals into the block;
- **the block changed behind us** (e.g. a pattern reload): load it.

Because the block is part of the saved pattern struct, the values follow a
pattern switch / reload and travel with a project save, exactly like stock
parameters. New patterns (no magic) start from whatever the mods currently
hold, so the sound never jumps.

## Verified in digiemu

Firmware `dn1-2.1z-d2535be9` (core-dn1-2.0a + the six suite mods, digictl 1.4):

- at boot the current pattern's block holds `DGX1` + the mod defaults
  (ring depth 51, EQ low 33, filter freq 64, …);
- editing a global + mark-dirty makes the tick write it to the block;
- poking the block makes the tick adopt it into the globals (the reload path);
- switching to pattern 2 gives a second block (own values); switching back
  restores pattern 1's values.

## Risks / open items

- The MIDI-track block is assumed never to be used by the firmware; it was zero
  across all 128 slots and untouched by the parameter mirror, but a configured
  MIDI track was not exercised. If it is ever reused, move the store to another
  zero run (the other three MIDI blocks `+0x1410`, `+0x17E0`, `+0x1BB0`, or the
  81-byte runs at `+0x0E7BA`/`+0x11009`/`+0x13858`/`+0x160A7`).
- Power-off persistence relies on the OS saving the pattern struct (auto-save
  of the temp project); not yet confirmed on hardware.
- The store is per pattern, not the "reload pattern" backup the OS may keep in
  a separate copy; the external-change adoption covers a reload that rewrites
  the struct.
