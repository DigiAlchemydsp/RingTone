# Digi Machine — hardware testing protocol (Digitone mk1 / Keys, OS 1.43)

A recoverable, step-by-step protocol for flashing and testing the **wavetable
machine** (`digimachine`) on real hardware. Follow it in order; every step has a
pass/fail and a recovery fallback. The bootloader is **never** changed, so the
unit is always recoverable with the stock OS.

> Status before you start: the build is **verified in digiemu** — it boots and
> settles (`dsp_running_u32=2`, 0 faults), and the engagement path is **proven
> end-to-end** (algorithm >= 8 -> shared P_ON=1 -> the Core B engine renders
> 64/64 non-zero audio frames; restoring an FM algorithm -> P_ON=0). The **UI
> route to select a wavetable slot is not solved yet** (see §5 caveat). Flashing
> modified firmware is at your own risk. Not affiliated with Elektron.

---

## 0. Prerequisites

- Digitone mk1 or Digitone Keys, **OS 1.43**.
- USB cable + **Elektron Transfer** installed.
- The stock OS file, kept on hand for recovery:
  `Digitone_and_Digitone_Keys_OS1.43.syx`.
- The files to flash (see §1).
- (Recommended) a way to record audio (the unit's USB or the main outs).

Back up anything you care about first (Transfer can back up projects/sounds).

---

## 1. What to flash

**Custom OS (.syx)** — via Transfer:

```
digitone_corea\releases\Digitone_OS1.43-digimachine.syx   (update this build)
```

The unit shows version **`2.4a`** for the current build (sha256 `8b707ef0…`).
Once the release is repackaged, the number in this file must be updated.

The `.elemod` set — only if you build the `.syx` yourself instead of using the
packaged one (add these with elekloader, with `core-dn1`):

```
elekloader-main\build\cores\core-dn1-2.0a.elemod          (required core)
digitone_corea\mods\digimachine\out\digimachine-0.6.elemod (Core A)
digitone_corea\mods\digimachine\dsp\digimachine.dspmod.json (Core B spec;
        pass with elekloader.dsp, not the elekloader GUI)
```

---

## 2. Recovery (know this before flashing)

The bootloader is untouched, so any bad flash is recoverable:

1. Power **off**.
2. Hold **FUNC** while powering **on** -> the startup menu appears.
3. Press **TRIG 4 (OS UPGRADE)**.
4. In Transfer, use **legacy OS upgrade mode** and send the stock
   `Digitone_and_Digitone_Keys_OS1.43.syx`.
5. Wait for it to finish; the unit boots stock.

If Transfer won't see the unit in OS-upgrade mode, retry the FUNC+power-on
sequence; do not power off mid-transfer.

---

## 3. Flash the custom OS

1. Power the unit on normally; connect USB; open Transfer; select/connect the
   Digitone.
2. Drag the custom `.syx` onto Transfer's drop area.
3. On the unit, press **YES** to confirm. **Do not power off** until it finishes
   and reboots.
4. Wait for the boot to complete.

**Pass:** the unit boots to the normal UI.
**Fail:** if it does not boot, go to §2 (recovery) and report.

---

## 4. Boot sanity

1. After flashing, let it boot fully (a few seconds).
2. Confirm the unit is responsive (keys change pages, transport toggles).
3. Confirm **`DSP BOOT FAILURE` is NOT shown** — the second CPU came up.

**Pass:** normal UI, no crash, no DSP failure.
**Fail:** note the symptom; recover (§2).

---

## 5. Engage the machine (the pivot)

The machine is meant to be hosted on the stock **SYN1** page: the extra
**algorithm slots 8..15** are the machine's on/off and table selection.

> **Caveat — read this first.** The firmware *does* engage the machine whenever
> the selected sound's algorithm is >= 8 (verified by directly writing the
> algorithm in the emulator), but the exact key/encoder gesture that selects
> algorithm 8..15 on the **stock SYN1 page** is **not yet confirmed**. On the
> emulator, turning the SYN1 encoder changed `Ratio C`, not `ALGORITHM`. So on
> hardware:

1. Open the **SYN1** page on a synth track (T1..T4).
2. Try to raise **ALGORITHM** past 7 (the descriptor and setters were widened to
   15, so 8..15 should be selectable). Options to try: turn each encoder
   (A–D), press-and-turn, and the PAGE key.
3. **Pass:** the ALGORITHM readout steps to 8..15 and a steady tone appears.
4. **Fail (likely until §5 of HANDOFF.md is solved):** the readout caps at 7, or
   the tone never appears. Record exactly which button/encoder was tried.

**This is the single open item before a meaningful hardware test.** Everything
downstream of the algorithm value is already verified.

---

## 6. Audio checks (once engaged)

1. Confirm a steady tone at the SYN-page tune (default ~440 Hz).
2. Change parameters and confirm:
   - **MORPH** changes timbre across wavetables
     (sine -> tri -> saw -> square -> pulse -> organ -> formant -> metallic);
   - **DETUNE** gives beating; **WIDTH** gives phase-offset character;
   - the three **sends** reach the FX mix.
3. While the sequencer is **playing**, the amp gate opens; stopped, it releases.
4. Return to an FM algorithm (0..7): the machine should go silent and the stock
   FM voice return.

**Pass:** tone stable, params do something, machine is in the mix, and turning
it off restores stock.
**Fail:** document (silence, wrong pitch, clicks, stuck tone).

---

## 7. Stress / integration

1. Run a pattern for several minutes with the machine on; listen for dropouts or
   the DSP resetting.
2. Switch between pages repeatedly; toggle the machine on/off.
3. Load a few projects/sounds; play the eight FM voices alongside the machine.
4. (If available) repeat on a Digitone **Keys**.

**Pass:** no crash, no audio dropout, DSP stays up.
**Fail:** recover (§2) and note the trigger.

---

## 8. Known caveats (expected, not bugs to chase)

- **`DSP BOOT FAILURE`?** The second CPU did not come up — recover.
- **The FM voice for slots 8..15 is not skipped yet.** This is a genuine
  limitation: the stock FM voice still renders alongside the machine for those
  slots. The FM-skip site is unknown (see HANDOFF.md); do not chase it in this
  test.
- **Per-note pitch is not wired yet**: the gate follows the transport; the pitch
  is the SYN-page tune, not the sequenced notes.
- **Settings are not saved per pattern** — they reset at power-off.
- The three **sends** currently sum into the mix source bus (they reach the FX
  mix) rather than mapping one-to-one to DELAY/REVERB/OVERDRIVE.

---

## 9. Report

Record and file:

- the flashed version and the `.syx` sha256;
- each step's pass/fail, especially §5 (which gesture selected a wavetable slot);
- audio clips (tone, morph sweep, sequencer run);
- photos of the SYN1 page showing the algorithm readout;
- any crash/reset with the sequence that produced it.

Publish the result next to `releases/README.md`; keep the stock `.syx` recovery
path documented.
