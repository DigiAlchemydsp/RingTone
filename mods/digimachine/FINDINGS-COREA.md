# Digi Machine — Core A findings (main CPU, section 3)

Digitone mk1 / Keys, **OS 1.43**. Confirmed addresses for the algorithm-slot
pivot (the machine lives on the SYN1 algorithm list, replacing the FM voice).
Marks: **[M]** measured from the image, **[L]** verified live in digiemu,
**[I]** inferred.

---

## 1. The algorithm parameter (SYN1)

| item | address | note |
|---|---|---|
| **ALGORITHM parameter descriptor** | **`0x4018EA20`** | 0x34-byte record; **range field at `+6` = `0x0700` (max 7)**; long name `Algorithm`, group `SYN`, short `ALGO` |
| descriptor next entry | `0x4018EA54` | `Ratio C` |
| logicalParamID 1 = algorithm | — | the SYN1 first sub-page is built by `std::vector<logicalParamID>::assign` (`0x40158F64`) from the id array `0x40197D00`, **count 1**; `*(u32*)0x40197D00 = 1` |
| other SYN1 id array | `0x40197CF0` | `[4,5,2,3,1]` (the operator/ratio sub-page) |
| SYN1 page class | vt **`0x401994A4`** | `FmSynthPageView`; **two sub-pages**: `(1/2)` algorithm diagram, `(2/2)` ratios; **PAGE** switches them **[L]** |
| FILT / AMP page classes | vt `0x4019931C` / `0x401991D4` | reused unchanged |

### Page machinery
- `FmSynthPageView` vtable `0x401994A4`; slot `+168` = **`0x400430C8`**
  `getParamDescriptor(this, id)`: reads the view's per-page descriptor vector at
  `view+104`, then calls the base resolver `0x4002ADE4`.
- The page's own `vector<logicalParamID>` is at `view+124` (begin) / `+128`
  (end) / **`+144`** (current index). `0x400430E8` special-cases ids `< 8` (FM
  operators); id 1 (algorithm) goes to the base resolver.
- Base resolver **`0x4002ADE4`** (`getParamDescriptor`, track-relative): ids
  `>= 8` offset by `0x30` (operator vs track params).
- Value read: `ParameterPageView::getParamValueToShow` **`0x4004B7E4`**.

---

## 2. The algorithm clamps (all must be widened / branched)

The setter and each consumer clamp the algorithm to **7**. Widening the
descriptor alone is not enough. The setter and descriptor are widened to 15;
the two resolver clamps are **branched around**: for `algo >= 8` they resolve
to the **entry-0** config/pointer (the 8-entry tables must not be indexed past
7), returning a safe in-bounds default until the FM-skip branch (section 3)
mutes those voices.

| clamp | address | bytes | role |
|---|---|---|---|
| setter #1 | `0x40025E44` | `74 07` -> `74 0f` | `0x40025E30` algorithm setter |
| setter #2 | `0x40025E4A` | `72 07` -> `72 0f` | same setter |
| config resolver | `0x40023268` | `72 07` (kept) | `0x4002325E` algo -> operator-config |
| config resolver | `0x4002326E` | `70 07` -> `70 00` | same (fall to entry 0) |
| pointer-table resolver | `0x400ACF8E` | `72 07` (kept) | `0x400ACF84` algo -> per-algo pointer |
| pointer-table resolver | `0x400ACF94` | `70 07` -> `70 00` | same (fall to entry 0) |

- **`0x40025E30`** — the algorithm setter: `if id<0 -> 0; if id>7 -> 7`; calls
  `0x40025C56` (a note/pitch table) and `0x4002325E`; stores via `0x40036660`
  (`base + 0x30`).
- **`0x4002325E`** — `algo -> operator-config`: `return base + algo*88 + 0x70`
  — an **8-entry table, 88 B each, at sound `+0x70`**. Must be **branched
  around** for `algo >= 8` (only 8 entries).
- **`0x400ACF84`** — `algo -> a0[0x4C + algo*4]`, another per-algorithm pointer
  table (8 entries).

### The algorithm getter / storage **[M]** **[L]**

**`*(0x4138E214) + 0x16119` is the selected sound's ALGORITHM value.** Confirmed
live in digiemu (2026-10-03) by pausing the GUI worker and poking it:

```
base = *(0x4138E214) = 0x407fc414
poke base + 0x16119 = 11  ->  shared P_ON = 1, machine audio 64/64 non-zero
poke back to 0            ->  shared P_ON = 0
```

`0x4138E214` is written at `0x40095EE2`. The routine at **`0x4009444A`** does
compute exactly this, disassembled:

```
4009444a  2079 4138e214   movea.l $4138e214.l, a0
40094450  203c 00016119   move.l  #$16119, d0
40094456  2030 0800      move.l  (a0, d0.l), d0   ; (0, A0, D0.L)
4009445a  4e75            rts
```

**Caveat:** hooking `0x4009444A` shows it is called ~2500x while drawing SYN1 but
**always returns 0** on the snapshot's selected sound. So either the page's
displayed "ALGO 1" is derived from elsewhere, or the sound genuinely has
algorithm 0 there and this getter serves a different caller. For engagement this
does not matter — the storage address is proven by the poke above. What remains
unknown is **which UI gesture writes it** (see §3a).

---

## 3. Per-voice config / FM prep

> **CORRECTED 2026-10-03.** The previous handoff called `0x400210A2` /
> `0x40034BA6` a "per-voice FM-skip site". That is **wrong**: these are **UI
> parameter setters**. `0x40025C56` is a param->pointer resolver;
> `0x40034BA6` clamps an operator index to <=63/78. They are not the render
> voice config. The real FM-skip site needs fresh RE and is **not** one of
> these addresses.

| item | address | note |
|---|---|---|
| per-voice config (old, suspect label) | `0x400210A2` | UI param setter path, not voice config |
| FM prep (old, suspect label) | `0x40034BA6` | operator index clamp <=63/78 |
| FM kernel (Core B-adjacent) | `0x40003ACC` (section 7) | 4-op chain |

**Routing plan (unchanged intent, new RE needed):** branch on `algo >= 8` at the
*real* per-voice render configuration so slots 8..15 skip the FM voice, and mark
the track for the machine. This is explicitly **out of scope for Stage 1**.

## 3a. UI selection of the algorithm (open)

The algorithm value is proven (§2) but the **UI gesture that writes it is not**.
Observed in digiemu on the settled SYN1 page:

- `T1` (42) / `SYN1` (21) taps are no-ops (that page is already open);
- turning **encoder A** (rotation code 1, wire channel 0) changed **`Ratio C`**
  (popup "Ratio C=7.00"), not `ALGORITHM`;
- `PAGE` (19) did not switch a sub-page in the synchronous harness.

Next: hook the algorithm setter **`0x40025E30`** (args: `$8(a7)` = param id,
`$10(a7)` = value) while turning encoders A–D and press-and-turn, to find the
param id and the gesture. Do not trust the prior "encoder A steps to Algorithm=11"
claim until reproduced.

---

## 4. Audio path (return)

| item | address | note |
|---|---|---|
| render ISR | `0x4009D100` | `ev_render_in`/`out` `0x4009D108` / `0x4009E51C` |
| voice-mix / send entry | `0x40097180` | builds the mix bus from `0x80004110` |
| **stock send call (hooked)** | **`0x400971E6`** (`jsr 0x4009A16A`) | replaced by `dmachine_bus_tap` |
| send/return ring | `0x4009A16A` | `0x8000EF70` -> `0x8000EB70` |
| bus FX | `0x400992F0`, `0x4009989C`, `0x4009A11C`, `0x4009A9DA` | EC70/ED70/... chains |
| **source bus (injection)** | **`0x8000EF70`** | the machine audio is added here, before the stock sends/FX |
| buses | `0x8000EB70` dry, `EC70`/`ED70`/`EE70`/`EF70` | 32 stereo frames |
| final out / in | `0x80001A00` / `0x80001800` | eDMA ch54 -> SSI1 STX0; ch52 <- SRX0 |
| master out writer | `0x40096E14` (call `0x4009E146`) | |

**Verified [L]:** with the machine ON, the source bus `0x8000EF70` and the
final output `0x80001A00` carry the oscillator.

---

## 5. Current Core A sites (mod `digimachine` 0.4)

```
0x400971E6  jsr -> dmachine_bus_tap     ; machine audio into source bus EF70
0x4018EA26  bytes 0700 -> 0f00          ; ALGO descriptor range, max 7 -> 15
0x40025E44  bytes 7407 -> 740f          ; setter clamp moveq #7 -> #15
0x40025E4A  bytes 7207 -> 720f          ; setter clamp moveq #7 -> #15
0x4002326E  bytes 7007 -> 7000          ; config resolver: algo>=8 -> entry 0
0x400ACF94  bytes 7007 -> 7000          ; pointer-table resolver: algo>=8 -> entry 0
```

**Status [L]:** firmware `2.4a` (0.6) boots, settles, `dsp_running=2`, **0
faults**; the engagement path is **proven end-to-end** by poking
`*(0x4138E214)+0x16119 = 11` (P_ON=1, machine audio 64/64). The stock SYN1 page's
`Algorithm` readout is widely reported to step past 7; the exact gesture is not
reproduced yet (see §3a).

**Still to do:** solve the UI selection of algorithm 8..15 (§3a); add the real
`algo >= 8` FM-skip branch (fresh RE — *not* the addresses previously named);
drive `dmachine_inc`/`dmachine_gate` from the voice note; draw the machine
controls on the SYN page for slots >= 8.
