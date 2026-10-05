# FAST AUDIO on the Digitone (findings + plan)

Status: **spike / plan, not built.** Compared against digihealth's FAST AUDIO
on the Digitakt mk1 (`elekloader-main/dist/digihealth-main/`).

## How FAST AUDIO works on the Digitakt

The render runs ~17 KB of code per block through an 8 KB I-cache: ~1000 misses
a block, ~30 cycles each. digihealth copies the hot block
`0x400716c0-0x4007629a` (~19 KB) into the on-chip SRAM the OS zeroes and never
uses (`0x80003360-0x80007fff`), rewrites the copy's references to itself, and
routes the render's calls into it through stubs that pick the copy or the
original. Same code, fewer wait states: measured render 537 -> 480 us/block,
DSP load 80.5% -> 72.0%. `build.py` computes, from the stock file: the block's
decodability, its self-reference fix-ups, and the call-site stubs
(`elekloader.isa.coldfire`).

## Why it is not a straight port

digihealth's own note: *"FAST AUDIO is not ported yet. The Digitone's render is
different code, and less of the SRAM is free."* Both are true and measurable.

### SRAM budget

`elekloader/devices/digitone_mk1.py` claims **no `.fast` area**; its note says
the free SRAM is `0x800058f0-0x80008000` = **10,000 B** (the Digitakt's copied
block alone is 19 KB).

**Update — a digiemu survey (settle, then `0x80000000-0x80010000`) finds a much
larger zero run:** `0x800058e4-0x8000cb18` = **29,236 B**, plus further runs
above it. Zero-after-settle is the same criterion the Digitakt's fast-audio SRAM
passed ("the OS zeroes and never uses"), so the 15.3 KB voice+FX block *fits*;
the 10 KB figure is a conservative note, not the limit. A per-page liveness
trace (not just zero) should confirm before use.

### Block self-containment (spike)

Runs of the FAST AUDIO planner (decode every insn; refuse un-implementable
insns, PC-relative operands or branches that leave the block) over candidate DN
blocks:

| candidate | size | planner result |
|---|---|---|
| render ISR `0x4009d100-0x4009e524` | 5156 B | **PCREL-OUT** at `0x4009d3d4` (jsr to `0x4009d0d4`) |
| render from `0x4009d0d0` | 5204 B | **BRANCH-OUT** `0x4009d0d0` -> `0x4009c58e` |
| render from `0x4009cf00`/`0x4009ce00`/`0x4009c800` | 5.9-7.5 KB | **BAD-INSN** (boundary is data) |
| voice mix helpers `0x40096b48-0x40096e14` | **716 B** | **OK**, 0 fix-ups |
| voice mix/master `0x40096e14-0x40097600` | 2028 B | **PCREL-OUT** `0x40096f70` -> `0x40096ad8` |
| FX chain `0x40098fa4-0x4009aa00` | 6748 B | **BRANCH-OUT** `0x4009a70c` jmp -> `0x400fb864` |
| voice + FX `0x40096e14-0x4009aa00` | 15340 B | **FIT-NO** (needs 15 KB, 10 KB free) |

So no single <=10 KB contiguous block contains the hot render path: it has
PC-relative calls to functions just below any natural start, tail `bra`/`jmp`
out, and data boundaries. The DT block was chosen because it *was*
self-contained; the DN's is not.

## Action plan

1. **Recover SRAM — done in the survey:** `0x800058e4-0x8000cb18` (29 KB) is
   zero after settle, so the 15 KB block fits. Remaining: a page liveness trace
   to prove nothing writes it, then add a `fast`/`sram` pair to the device
   profile (`0x800058e4-0x8000cb18`).
2. **Planner port.** `digihealth/build.py` + `fastaudio.s` are device-agnostic
   except the block, SRAM window and `dn143.inc` call list. Port them to a
   `fast-audio-dn` mod: `fast_audio = {block:[lo,hi], sram:[dst,end],
   call_sites:[[site,op,target],...]}`; reuse `plan_block`, `stubs_source`,
   `generate()`.
3. **Pick the block the planner accepts.** Likely the render ISR (5.2 KB) with
   its start extended below `0x4009d0d4` to swallow the PC-relative callee, plus
   the `0x40096e14` voice-mix region (2.0 KB) if the budget allows; stub the
   calls in from outside. Anything it cannot copy (a `jmp` out, e.g.
   `0x4009a70c`) is a candidate for a stub, which needs a small planner change
   (`jmp`-out -> `jmp` stub, not refused).
4. **Stub the Core sites we own.** Our `digifilter` site `0x4009e13e` is inside
   the render; if the render is copied, the copy calls the *stub*, so
   `digifilter` must be installed so the stub lands in the copy (order the mods,
   or keep the site outside the copied range).
5. **Validate like digihealth did:** bit-exact audio vs stock over several
   minutes and scenarios; the copy's checksum watchdog; boot on a recoverable
   unit.

## Payoff estimate

The DT won ~12% render time. The DN render is bigger and runs on a faster DSP
than the DT had, but the same I-cache band applies: a comparable single-digit
percent to low-double-digit percent cut in the main CPU's audio load. It is the
right lever for the UI-freeze symptom **if** step 1 finds the SRAM; otherwise
the Core B offload (`SECTION7-CORE-B.md`) is the fallback.
