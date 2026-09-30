# Digitone mk1 — DSP reference

Everything about audio DSP on the **Digitone mk1 / Digitone Keys, OS 1.43**:
the two CPUs, the link between them, the FM voice engine, the main-CPU FX/mix
render, the buffers and eDMA/SSI path, the fixed-point conventions, how to write
a DSP mod on either CPU, and the reverse-engineering method.

Target file: `Digitone_and_Digitone_Keys_OS1.43.syx`, main OS sha256
`3831a477…` (2,732,208 bytes at `0x40000400`); DSP program **section 7**
(126,352 bytes, loaded at `0x40000400` on the second CPU).

Confidence: **[M]** measured from the image / live, **[D]** documented in
digiemu, **[I]** inferred. Addresses are OS 1.43; other releases move.

---

## 1. The two CPUs (the "two DSP cores")

| | **Core A — main CPU** | **Core B — second CPU ("DSP")** |
|---|---|---|
| part | ColdFire MCF5441x | ColdFire MCF5441x |
| program | MAIN OS, section **3**, `0x40000400` | section **7**, `0x40000400` on its own bus |
| loaded by | the updater | section **6** (serial-boot loader) over DSPI2 |
| does | UI, sequencer, +Drive, **effects and the mix** | **8 FM voices** (4-op, EMAC, Q1.31) |
| render entry | ISR `0x4009D100`, vector 191 (INTC1 src 63, software-forced) | vector 96 handler `0x400008FA` (DTIM0 capture) |
| block | 32 frames, 48 kHz, ~1500/s | 8 voices × 32 samples per block |
| output | SSI1 over eDMA ch54; buffer `0x80001A00` | shared RAM `+0x3A0..+0x79F` |

The firmware's own string `DSP BOOT FAILURE` is at `0x401D9082`. **[M]**

**Key consequence:** the **per-voice FM synthesis, operator waveforms,
algorithms, envelopes and per-voice filters run on Core B**, which elekloader
historically could not touch. Core A only owns the **effects and the mix**.
Voice behaviour can still be steered from Core A through the parameter frame it
sends to Core B.

### The DSP link (Core A ↔ Core B) **[D][M]**

- **Shared RAM:** 128 KB dual-port. Main CPU sees it at `0x10000000`; the DSP at
  `0x00000000`.
- **Frame:** `+0x000..+0x39F` = voice parameters (main → DSP, **stride 0x9E**);
  `+0x3A0..+0x79F` = 8 voices × 32 samples × int32 (DSP → main).
- **Block clock:** each 32-frame block, the SSI1 TX DMA interrupt (eDMA ch54,
  vector 174, `0x4009C2E4`) toggles main `PA4` (`0xEC094018`/`0xEC094024`, bit 4)
  → the DSP's DMA-timer-0 capture (**vector 96**) runs the render.
- **Reverse line:** DSP `PG2` (`0xEC09401E`/`0xEC09402A`, bit 2) → main edge
  port, **vector 68**.
- **Reset:** main `PB6` (`0xEC094019`/`0xEC094025`, bit 6) holds the DSP reset.
- **Boot task:** `dsp_boot_task` `0x4008D56C` streams section 6 + section 7 out
  of DSPI2 (`0xEC038000`) as an SPI slave, then releases the reset. Section 6
  loads section 7 at `0x40000400` and jumps to `0x40000B92`.
- **Status word:** `0x4137B720` — `0` = booting, `1` = `DSP BOOT FAILURE`,
  `2` = running. Request semaphore `0x4137B70C` (posted by `0x400019A0`).
  Main edge handler `0x4008D850`.
- After boot the main CPU never waits on the DSP.

---

## 2. Core A — the FX and mix render (main CPU)

### 2.1 The render ISR **[M]**

| step | address | detail |
|---|---|---|
| entry | `0x4009D100` | `linkw %fp,#-184`; `moveml %d0-%a5` |
| `ev_render_in` | `0x4009D108` | core's site (stock `move.l #0x7fffffff,d0`) |
| clear force bit | `0x4009D10E` | `and.l #0x7fffffff,0xFC04C010` (INTFRCH1[31]) |
| pick DMA half | `0x4009D114` | reads ch54 SADDR `0xFC0456C0`, ch52 DADDR `0xFC045690` |
| fetch voices | `0x4009D162` | eDMA **ch47** (SSRT): `SAR=0x100003A0` → `DAR=0x80004110`; start `0xFC04401E` |
| save EMAC | `0x4009D1A2` | `movel macsr/accext01/accext23/acc0-3/mask` to `fp@(-64)` |
| voice mix / sends | `0x40097180`–`0x40097560` | pan/level into the buses |
| bus FX | `0x40098FA4`, `0x400992F0`, `0x4009989C`, `0x4009A11C`, `0x4009A9DA`, `0x40098110` | delay/reverb/overdrive chains |
| upload params | `0x4009C378`, `0x4009E00C` | eDMA ch47: `SAR=0x80001C00` → `DAR=0x10000000` |
| modulation / LFO | `0x4009B81A` | reads ADC `0xFC094002`, table `0x401AB10C`, EMAC smoothing |
| master out | `0x40096E14` (called `0x4009E146`) | writes the SSI half |
| `ev_render_out` | `0x4009E51C` | core's site; stock `moveml %fp@(-184),%d0-%a5; unlk; rte` (`0x4009E524`) |

### 2.2 eDMA and SSI1 **[M]**

| channel | TCD base | role |
|---|---|---|
| **47** | `0xFC0455E0` | SSRT: voices `0x100003A0`→`0x80004110`; params `0x80001C00`→`0x10000000` |
| **54** | `0xFC0456C0` | SSI1 TX: `SADDR=0x80001A00`, `DADDR=0xFC0456D0` (SSI1 `STX0` `0xFC0C8000`), `SLAST=-512`, CITER/BITER 64, `CSR=6` (INT_HALF\|INT_MAJOR) |
| **52** | `0xFC045680` | SSI1 RX: `DADDR=0xFC045690=0x80001800`, from SSI1 `SRX0` `0xFC0C8008` |
| — | `0xFC0C8000` | SSI1 (audio out/in); init at `0x4000117E`/`0x400011FA` |
| — | vector 174 | ch54 complete (`0x4009C2E4`); forces the render (vector 191) |

### 2.3 Buffers and structures **[M]**

| name | address | shape |
|---|---|---|
| DSP voices in | `0x80004110` | 8 × 32 int32 (1024 B) |
| stereo buses | `0x8000EB70` dry, `0x8000EC70`, `0x8000ED70`, `0x8000EE70`, `0x8000EF70` | 32 stereo frames (256 B) each |
| **final output** | `0x80001A00` | 512 B double buffer; the render writes a **256 B half** at `+0x000` or `+0x100` |
| audio input | `0x80001800` | 512 B (SSI1 RX) |
| main→DSP param frame | `0x80001C00` | source of the ch47 param upload |
| render state | `0x80003F0C`, `0x80003F10`, `0x80003F54` | per-track at `0x80003F54 + 0x18 + t*0x146` |
| per-voice table | `0x800034C4` | +705 words (0x2C1) |
| per-track FX/send | `0x80005434` | stride 20, 4 tracks; mute/send `0x800054D4`; masks `0x41392798`, `0x41392714` |
| FX enable bytes | `0x80003FD9/DA/DB` | per-track FX flags (clamped at `0x4009CC32`) |
| tempo | `0x40236384` | set `0x4009C82C` (clamped 3600..36000) |
| per-voice param stride | `0x9E` (158) | matches Core B's frame stride |
| per-track sound | `0x146` (326) | also the Core B-adjacent sound record size |

### 2.4 EMAC **[M]**

Core A's render uses the ColdFire EMAC (`macl`, `msacl`, `movclr.l`, `satsl`)
and **saves/restores the whole EMAC state** around the render (`MACSR`,
`ACCext01`, `ACCext23`, `acc0..acc3`, `MASK`). A mod that uses EMAC must do the
same, or call its firmware helpers that already do.

---

## 3. Core B — the FM voice engine (section 7)

### 3.1 Layout **[M]**

| piece | address | what |
|---|---|---|
| load / entry word | `0x40000400` = `0x40000B92` | where the loader jumps |
| VBR | `0x40000000` (set `0x40000A76`) | all 256 vectors → `rte` stub `0x40000404` |
| reset / vector 96 (boot) | `0x40000406` | sets DTIM0, flag `0x400166E0` |
| boot / init | `0x40000B92` | stack `0x48000000`, clocks, eDMA, CACR `0xA50CE100` |
| SRAM init | `0x40000482`, `0x400004D8` | copy/zero the 64 KB SRAM `0x80000000`–`0x80010000` |
| FPGA bring-up | `0x4000050E`, `0x40000568`, `0x400006CC` | bitstream over DSPI1 `0xFC03C000` |
| handshake | `0x40000A30`–`0x40000B90` | `'HO'`/`'HA'` (0x484F/0x4841), expect `'B0'` (0x4230), `0xA5A5`; installs the render trampoline into vector 96 |
| idle | `0x40000B90` | `bra.b *` between interrupts |
| **render (vec 96)** | **`0x400008FA`** | copies params in, runs voices, copies audio out |
| per-voice prep | `0x40003364` | 8 voices, internal state stride `0x188` at `0x40016934` |
| **FM kernel** | **`0x40003ACC`** | 4 `macl` chains + `movclr.l`, 32 iterations |
| voice state update | `0x400038C2` | gate/EMAC state |
| clear / zero | `0x40003890`, `0x40003BC0` | state clear |
| pitch / ratio | `0x4000200A`, `0x40001FDE` | per-voice field at `+0x66`, `mulsl #0x9E` |
| init constants | `0x40000BFC` | 48000, 96000, 1500; tables `0x400166E8`/`0x400167C8` |
| algorithm/routing table | `0x40003BD4`+ | sequences of operator ids 0..3 |
| voice buffer ptrs | `0x40003C34` | `0x8000EF58`, `0x8000EB54`, `0x8000E750` |

### 3.2 The FM kernel **[M]**

`0x40003ACC` is a **four-operator FM chain** (per voice, per sample):
four `macl`/`msacl` into `acc0..acc3`, operator slots **0x80 bytes apart**
(`0x000/0x080/0x100/0x180/0x200/0x280/0x300/0x380/0x384`), `movclr.l` to persist
phase, 32 iterations per block, Q1.31 scaling (`0x7D70A3D7` ≈ 0.98,
`0x0AAAAAAB` ≈ 1/6). Internal voice stride `0x188` (392 B). **[M]**

### 3.3 The shared-RAM frame **[D][M]**

| offset | size | direction | contents |
|---|---|---|---|
| `+0x000..+0x39F` | 928 B | main → DSP | voice parameters, **stride 0x9E** per voice |
| `+0x3A0..+0x79F` | 1024 B | DSP → main | 8 voices × 32 samples × int32 |

The render copies the parameter frame in, renders, and copies `0x400` bytes from
its SRAM `0x80000E00` to `+0x3A0`.

### 3.4 SRAM and free space **[M]**

- DSP SRAM: `0x80000000`–`0x80010000` (64 KB). Work areas: `0x80000330`,
  `0x800003A0`, `0x80000DE0`, output `0x80000E00`; state at `0x8000EF58`,
  `0x8000EB54`, `0x8000E750`, `0x8000F45C`, `0x8000F464`.
- **Free in section 7:** `0x4001F048`–`0x4001F190` (328 B) is zero and
  unreferenced by any in-image absolute operand. The larger zero run
  `0x4000861A`–`0x40017CE0` is **mostly workspace** — the boot zeroes
  `0x400166E0..0x40017700` and code references it (51 abs refs). Choose a code
  cave with an emulator liveness trace, not a static scan.

---

## 4. Fixed-point conventions and helpers

- **Core A output** (the SSI buffer `0x80001A00`): `int32`, **24-bit
  left-justified** (SSI1 is 24-bit). The factory pattern peaks around `2^21`.
- **Core B**: **Q1.31** on the EMAC.
- **Helpers** (`src/corea.h`), no 64-bit multiply, no library call:
  ```c
  static inline int dn_q15(int x, int c) { return (x >> 15) * c; }   /* x*c/2^15, c is Q15 */
  static inline int dn_q14d(int x, int d){ return (x >> 14) * d; }   /* x*(1 + d/2^14), d small Q14 */
  ```
- **Which output half is live** (master inserts):
  ```c
  #define DN_DMA_CH54_SADDR (*(volatile unsigned *)0xFC0456C0u)
  static inline unsigned dn_out_off(void)   /* ev_render_in: the half this block writes */
  { return (DN_DMA_CH54_SADDR < 0x80001B00u) ? 0x100u : 0u; }
  ```
- **EMAC** (Core B and Core A kernels): preserve `MACSR`, `MASK`, `ACCext01`,
  `ACCext23`, `acc0..acc3` exactly.

---

## 5. Writing a **Core A** DSP mod (main-CPU FX/mix)

Two patterns, both **subscriptions only** (so they combine with everything):

1. **Master insert (combinable).** `ev_render_in` stores `dn_out_off()`;
   `ev_render_out` processes `0x80001A00 + off` (256 B, 32 stereo frames) in
   place. This is how `digieq`/`digiring`/`digiglitch`/`digimeter` work.
2. **`jsr` site** in the render where your buffers are live (e.g. the voice mix
   `0x40097180`, the master stage `0x4009E100`–`0x4009E400`, or wrapping the
   output writer `0x40096E14` at `0x4009E146`). One *distinct* free instruction
   per mod; `patch --check` proves no overlap.

`ev_render_in`/`ev_render_out` run at **interrupt level**: keep them short, no
blocking firmware calls. A master insert can also tap `0x80004110` (per-voice)
or a bus (`0x8000EC70…`) instead of the final output.

### Worked examples (in this repo)

- `mods/digimeter` — `ev_render_in`/`out` peak metering (log bars), read by the page.
- `mods/digieq` — one-pole low/high tilt, Q14 gains, interpolated per frame.
- `mods/digiring` — 256-entry Q15 sine ring/AM, depth/freq interpolated.
- `mods/digifold` — triangle wavefolder (gain, then reflect into `[-T,T]`),
  amount 0 = 1.0x (bypass).

The master chain order is set by the `ev_render_out` orders:
**ring (50) → EQ (55) → fold (60)**.

---

## 6. Writing a **Core B** DSP mod (section 7)

elekloader now patches section 7 (raw: the stored bytes are the image). Tool:

```powershell
python -m elekloader.dsp --stock Digitone_and_Digitone_Keys_OS1.43.syx `
    --spec my-dsp.dspmod.json [--mod core-dn1-2.0a.elemod --mod my-mod.elemod ...] `
    --out custom.syx --version 2.0d
```

A `.dspmod.json` names whole-instruction sites in section-7 space:

```json
{"id":"my-dsp","version":"1.0","device":"digitone-mk1","os":"1.43",
 "sites":[
   {"addr":"0x40003ACC","stock":"<exact bytes>","op":"jsr","target":"0x4001F048"},
   {"addr":"0x4001F048","stock":"0000...","op":"bytes","new":"<code hex>","kind":"code"}
 ]}
```

`op` is `bytes` / `jsr` / `jmp` / `keep2` / `ptr`, with an **absolute** `target`
(no linker on Core B). **Rules:** keep the entry word `0x40000B92`, the
handshake and the `0x400008FA` render contract (the tool refuses an entry
change); preserve EMAC state; return to the idle loop `0x40000B90`; place code
in a **validated** cave. `--check` stops before writing.

The Digitone's second CPU is ColdFire, so the **same `m68k-elf` toolchain**
builds Core B code.

---

## 7. Reverse-engineering method

- **Extract** the OS sections (incl. section 7):
  `python -m emu.extract Digitone_and_Digitone_Keys_OS1.43.syx -o DIR` (digiemu).
- **Disassemble** with the ColdFire V4e ISA:
  `m68k-elf-objdump -D -b binary -m m68k:cfv4e --adjust-vma=0x40000400 section_3_MAIN_OS.bin`
  (`m68k:cfv4e` on binutils 2.23.1; `-m 5407` also decodes ColdFire on other
  binutils). Section 7 loads at `0x40000400`, so file offset = address − base.
- **Find code:** `objdump` + `grep`; the ColdFire EMAC instructions (`macl`,
  `msacl`, `movclr`) mark the DSP kernels.
- **RTTI:** class names via `cstr(*(*(vptr-4)+4))`; resolve name → typeinfo →
  vtable by scanning for the pointers.
- **Live:** digiemu (`C:\Users\benan\Music\ELEKTRON\digiemu-main`, patched-Unicorn
  venv). `emu.portable --add <syx> --yes` boots and settles; `emu.dsplink.DspCpu`
  runs section 7 deterministically in batch; `emu.extract` reads the patched
  section 7 back out.

---

## 8. Quick address reference

**Core A**
```
render ISR        0x4009D100   core render_in 0x4009D108 / render_out 0x4009E51C
output writer     0x40096E14   (call site 0x4009E146)
voice mix/sends   0x40097180-0x40097560
force clear       0xFC04C010 bit31
SSI1              0xFC0C8000 (STX0 +0x00, SRX0 +0x08)
eDMA ch54         0xFC0456C0  SADDR=0x80001A00  DADDR=0xFC0456D0
eDMA ch52         0xFC045680  DADDR=0x80001800
eDMA ch47 (SSRT)  0xFC0455E0  voices 0x100003A0->0x80004110; params 0x80001C00->0x10000000
output buffer     0x80001A00  (512 B; halves +0x000/+0x100, 256 B each)
audio in          0x80001800   param frame 0x80001C00
voices            0x80004110   buses 0x8000EB70/EC70/ED70/EE70/EF70
render state      0x80003F0C/10; per-track 0x80003F54 (stride 0x146)
per-voice table   0x800034C4 (+705 words); per-voice param stride 0x9E
per-track FX/send 0x80005434 (stride 20); FX enable 0x80003FD9/DA/DB
LFO / mod apply   0x4009B81A (ADC 0xFC094002, table 0x401AB10C)
tempo             0x40236384 (set 0x4009C82C)
master FX names   DELAY 0x401E2058 REVERB 0x401E205E OVERDRIVE 0x401E2065
```

**Core B (section 7; addresses on the DSP bus)**
```
load/entry  0x40000400 = 0x40000B92      idle 0x40000B90
VBR 0x40000000   reset/vec96 0x40000406   handshake 0x40000A30
render vec96 0x400008FA                    FM kernel 0x40003ACC
voice prep 0x40003364 (stride 0x188)       voice update 0x400038C2
clear 0x40003890 / 0x40003BC0              pitch/ratio 0x4000200A / 0x40001FDE
init consts 0x40000BFC                     algo table 0x40003BD4  buffers 0x40003C34
SRAM 0x80000000-0x80010000 (work 0x80000330/03A0/0DE0, out 0x80000E00)
free cave 0x4001F048-0x4001F190 (328 B)
shared RAM main 0x10000000 = DSP 0x0
  params +0x000..+0x39F (stride 0x9E)   voices +0x3A0..+0x79F
sync: PA4 0xEC094018/24 -> vec96; PG2 0xEC09401E/2A -> vec68; reset PB6 0xEC094019/25
status 0x4137B720 (0 boot, 1 fail, 2 running); boot task 0x4008D56C
DSPI2 (to main) 0xEC038000; DSPI1 (FPGA) 0xFC03C000
```

---

## 9. Gotchas

- **Core B is off-limits to per-voice DSP unless you patch section 7.** The
  per-voice filter/FM lives there; Core A only does FX/mix.
- **EMAC state:** save/restore `MACSR`/`MASK`/`ACCext`/`acc0..3`.
- **No C library / no FPU** (MCF5441x): integer only; use `dn_q15`/`dn_q14d`.
- **ColdFire:** max instruction 6 bytes; `-mcpu=54455`; `lsl.l #N` only 1–8; no
  `dbra` on this gas.
- **Block budget:** ~1500 blocks/s at 48 kHz; measure with
  `emu.portable --check --timing`.
- **`ev_render_*` is interrupt level:** short, non-blocking.
- **Core B caves:** validate liveness in the emulator; keep the entry/handshake/
  render contract.
- **Never ship firmware bytes:** sites carry `stock` hashes, not the image.
