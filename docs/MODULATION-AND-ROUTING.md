# Findings: LFO destinations for our params, and moving our chain before the FX

Status: **spike / plan.** OS 1.43, DIGI suite. Both are Core A (main CPU) jobs.

## 1. Our chain is currently *after* the master effects

Our inserts (`digiring`, `digieq`, `digifold`) are `ev_render_out` subscribers:
they process the finished SSI output half at `0x80001a00` (`DIGI`'s `dn_out_off`),
which the render writes **last**, after the bus effects. So ring/EQ/fold sit
after the delay/reverb/chorus (they shape the whole output including tails).

### The master render (`0x40096e14`, called once a block)

Measured bus calls (args on entry) and FX entry points:

```
0x400971e6  FUN_4009a16a(0x8000eb70, 0x8000ef70, track*)   ; dry <- main mix
0x40097268  FUN_400992f0(0x8000ec70, 0x8000ef70, track*)   ; send A
0x40097318  FUN_4009989c(0x8000ed70, 0x8000ef70, track*)   ; send B
0x4009731e  FUN_4009a11c(send B ...)
0x400973fc  FUN_4009a9da(0x8000ef70, ...)                  ; bus op
0x40097422  FUN_40096b92(0x8000ef70, 0x8000ee70)           ; main mix -> wet
0x4009751a  FUN_4009786c(0x8000eb70, 0x80004110, ...)      ; dry <- voices
master sum  0x400974c0  reads 0x8000ee70 + 0x8000ef70 -> output
```

Buses (`DSP.md`): **dry `0x8000eb70`**, sends **`0x8000ec70`/`0x8000ed70`/`0x8000ee70`**,
**main mix `0x8000ef70`**. The FX chains are `0x40098fa4`, `0x400992f0`,
`0x4009989c`, `0x4009a11c`, `0x4009a9da`.

### The move

To place ring/EQ/fold **before** the sends/FX, process the **main mix
`0x8000ef70`** after the voices are in it and before the first send
(`0x400971e6`) — a `jsr` site in `0x40096e14` (a distinct whole instruction).
Alternatively process the **dry bus `0x8000eb70`** right after `0x4009751a`, so
our chain shapes the dry signal that the output sums (but *not* the FX returns).

Two things must be confirmed before writing it:
1. Disassemble `FUN_4009a16a` / `FUN_400992f0` to confirm which operand is the
   read and which the write (is `ef70` the pre-FX mix or a post-FX bus?).
2. A `jsr` site that does not collide with `core`/`digifilter` (ours are
   `0x4009d108`, `0x4009e51c`, `0x4009e13e`).

Cost is unchanged (32 frames); only the position in the chain moves. The
`ev_render_in`/`out` insert code already exists — the change is "which buffer,
which site".

## 2. Adding our params as LFO destinations

### The Digitone live value record — FOUND (live)

The FLTR page writes a **per-voice live parameter record** directly:

```
record(v) = 0x80003544 + v * 0x9E        (v = 0..7, stride 0x9E)
```

mapped live by turning each FLTR encoder and diffing the array:

| off | field | off | field |
|---|---|---|---|
| `+0` | FREQ (index<<8, low byte fraction) | `+8` | DEC |
| `+2` | RESO | `+10` | SUS |
| `+4` | ENV DEPTH (biased 0x4000) | `+12` | REL |
| `+6` | ATK | `+156 (0x9C)` | TYPE |

All 8 voices changed together when track 1's FREQ moved, so each voice carries
its track's live value. (This is the DN's analogue of the DT's
`0x80002760+0x6a*v`; the DT's `0x80*` constants do **not** apply.)

### What is still missing

- **Where the LFO writes.** If the LFO applies to this per-voice record (or a
  per-track record the render copies into it), reading `+off` gives the
  LFO-modulated value. Need to find the LFO tick + apply loop and confirm the
  target.
- **A spare destination.** The LFO destination is a real slot. To avoid also
  modulating the stock engine, the destination list must expose a slot the
  stock ignores (DN RAM-only slots `46..52`, DT convention) — the destination
  table still has to be located (LFO page descriptors around `0x4018dc84`, the
  `DESTINATION` title at `0x401ec36a`; refs at `0x4023bdd0`).

### Bridge design (once the two above land)

A small subscriber (`ev_tick`, 30 Hz, cheap) reads the record word at the chosen
destination slot for the target track/voice and maps it to a digifilter/digiring/
digieq/digifold global. Because the FLTR FREQ word is `index<<8` with a
fractional low byte, an LFO on FREQ already gives a smooth 0..127+ mod source to
bridge to any of our params.

## 2b. Original LFO notes (kept)

The LFO page is descriptor-driven. Measured:

- Page strings `LFO1` `0x401d621a`, `LFO2` `0x401d621f`, `SPD` `0x401d63e4`,
  `MULT` `0x401d63f3`, `FADE` `0x401d6404`; the destination selector's title
  `DESTINATION` `0x401ec36a`.
- The LFO param descriptors live around **`0x4018dc84`..`0x4018e1xx`** (the
  `LFO1`/`LFO2`/`SPD`/`MULT`/`FADE` pointers point there).
- Destination = a parameter-slot reference; the apply writes the per-track
  value array `0x80001502 + 106*v + 2*s` (RE_NOTES §3), before the block's
  parameter frame is built.

To make our globals modulatable there are two routes:

1. **Extend the destination list** (clean, big): add descriptors for our params
   to the destination table, so they appear in the selector, and hook the apply
   so a destination in our range writes our global instead of a slot. Needs the
   destination table's address/length and the apply loop — the "`digimatrix`
   spike" (`plans/digimatrix`): find the LFO tick + the apply loop, then add
   destinations. High effort, high value.
2. **A bridge mod** (small, self-contained): don't touch the stock selector. The
   stock LFO still targets a **spare sound slot** (e.g. the RAM-only slots
   `46..52`, or one of `0x21..0x25` we already reuse); a new mod reads that slot's
   per-track value each block and adds it to our param. The user picks the
   destination in the stock LFO page (a slot we co-opt), and the mapping is
   documented. Lower risk, no stock UI code touched.

**Recommendation:** do (2) first — it needs only the per-track value array
(`0x80001502 + 106*v + 2*s`, already known) and a per-block `ev_tick`/render
subscriber, and gives LFO → our params without reverse-engineering the whole
modulation system. (1) is the proper long-term fix.

### Suggested bridge mapping

| stock LFO destination (spare slot) | drives |
|---|---|
| `0x24` SRR (RAM-only, unused for our types) | ring depth |
| `0x25` spare | fold amount |
| `0x21` Base | EQ low |
| `0x22` Width | EQ high |

(These are per-track; the LFO of track *t* would drive voice/track *t*'s value.
A master target takes a track's value as the modulation source.)

## Next

1. Confirm the bus direction (`FUN_4009a16a`) and pick the `jsr` site → move the
   chain pre-FX.
2. Build the bridge mod for LFO → params (route 2).
