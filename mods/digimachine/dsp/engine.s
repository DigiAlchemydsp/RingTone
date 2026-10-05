| Digimachine — Core B (Digitone mk1, second CPU) wavetable engine.
|
| Hooked over the render's voice-block copy (0x40000A0A jsr 0x40003848). Renders
| the wavetable machine's 32 stereo frames into shared +0x880, then tail-calls
| the displaced copy so the stock FM voices still publish.
|
| Oscillator: two detuned oscillators (incA, incB), each read at two phases
| offset by WIDTH; the four table reads are summed and morph-blended between
| two adjacent of 8 tables (nearest table for v1). Then a one-pole low-pass
| (FILT) and a block-rate ADSR amp envelope.
|
| ColdFire note: lsl/asr immediates are 1..8 only; long indexed addressing is
| (%aN,%dN:l) only (the index must be a byte offset).
|
| EMAC + d0-d7/a0-a6 are saved and restored.

        .set    SH_BASE,   0x00000000
        .set    P_MAGIC,   0x7fc
        .set    DM_MAGIC,  0x444d4143
        .set    P_ON,      0x800
        .set    P_INC,     0x804
        .set    P_DET,     0x808
        .set    P_WIDTH,   0x80c
        .set    P_MORPH,   0x810
        .set    P_LEVEL,   0x814
        .set    P_PAN,     0x818
        .set    P_FTYPE,   0x81c
        .set    P_FFREQ,   0x820
        .set    P_FRESO,   0x824
        .set    P_FENV,    0x828
        .set    P_ATK,     0x82c
        .set    P_DEC,     0x830
        .set    P_SUS,     0x834
        .set    P_REL,     0x838
        .set    P_GATE,    0x83c
        .set    A_AUDIO,   0x880
        .set    TBL,       0x1000

        .set    ST,        0x8000F800
        .set    ST_PH,     0
        .set    ST_PH2,    4
        .set    ST_LP,     8
        .set    ST_ENV,    12

        .set    SV_MACSR, 60
        .set    SV_ACC0,  64
        .set    SV_ACCEX, 68

        .text
        .balign 2
        .globl  digimachine_engine
digimachine_engine:
        lea     -80(%sp), %sp
        movem.l %d0-%d7/%a0-%a6, (%sp)          | 60 bytes
        move.l  %macsr, %d0
        move.l  %d0, SV_MACSR(%sp)
        move.l  %acc0, %d0
        move.l  %d0, SV_ACC0(%sp)
        move.l  %accext01, %d0
        move.l  %d0, SV_ACCEX(%sp)

        move.l  #0x20, %macsr
        moveq   #0, %d0
        move.l  %d0, %acc0
        move.l  %d0, %accext01

        | Core A writes DM_MAGIC last after uploading the tables/engine; before
        | that, shared +0x8000 holds nothing executable, so a render that races
        | the upload must not fall through. Bail to the displaced copy instead.
        movea.l #SH_BASE+P_MAGIC, %a0
        move.l  %a0@, %d0
        cmp.l   #DM_MAGIC, %d0
        bne.w   .Loff

        movea.l #SH_BASE+P_ON, %a0
        tst.l   %a0@
        beq.w   .Loff

        | -------- params --------
        movea.l #SH_BASE+P_INC, %a0
        move.l  (%a0), %d3                      | d3 = incA
        movea.l #SH_BASE+P_DET, %a0
        move.l  (%a0), %d2
        move.l  %d3, %d1
        asr.l   #8, %d1                         | incA>>8 (detune Q14 -> /2^14 via two steps)
        asr.l   #6, %d1                         | incA>>14
        muls.l  %d2, %d1
        add.l   %d3, %d1
        move.l  %d1, %a1                        | a1 = incB (kept off d1, which is scratch below)

        movea.l #SH_BASE+P_WIDTH, %a0
        move.l  (%a0), %d5
        lsl.l   #8, %d5
        lsl.l   #8, %d5                         | d5 = width << 16
        lsl.l   #2, %d5                         | d5 = width << 18

        | ---- morph: index (d0) -> a3 table base, fraction -> d7 ----
        movea.l #SH_BASE+P_MORPH, %a0
        move.l  (%a0), %d0
        move.l  %d0, %d7
        and.l   #0xff, %d7                      | d7 = blend fraction 0..255
        asr.l   #8, %d0                         | d0 = index 0..7
        cmp.l   #6, %d0
        ble.s   1f
        moveq   #6, %d0                         | clamp so index+1 stays in 0..7
        move.l  #255, %d7
1:
        | table base a3 = TBL + d0*512 ; a5 = a3 + 512 (next table)
        lea     SH_BASE+TBL, %a3
        lsl.l   #8, %d0
        lsl.l   #1, %d0                         | *512
        adda.l  %d0, %a3
        lea     512(%a3), %a5

        | phases: d4 = phaseA ; a2 = phaseB (32-bit)
        movea.l #ST, %a6
        move.l  (%a6)+, %d4
        movea.l (%a6)+, %a2

        lea     SH_BASE+A_AUDIO, %a0
        moveq   #32, %d1                        | frame counter (data reg: SUBQ sets Z)

.Lsample:
        | ---- sum of four reads from table i (d2) and i+1 (d6) ----
        moveq   #0, %d2
        moveq   #0, %d6

        | r0: phaseA
        move.l  %d4, %d0
        lsr.l   #8, %d0
        lsr.l   #8, %d0
        lsr.l   #8, %d0                         | d0 = phaseA >> 24 = index 0..255
        lsl.l   #1, %d0                         | word byte offset
        move.w  (%a3,%d0:l), %d0
        ext.l   %d0
        add.l   %d0, %d2
        move.w  (%a5,%d0:l), %d0
        ext.l   %d0
        add.l   %d0, %d6

        | r1: phaseA + width
        move.l  %d4, %d0
        add.l   %d5, %d0
        lsr.l   #8, %d0
        lsr.l   #8, %d0
        lsr.l   #8, %d0
        lsl.l   #1, %d0
        move.w  (%a3,%d0:l), %d0
        ext.l   %d0
        add.l   %d0, %d2
        move.w  (%a5,%d0:l), %d0
        ext.l   %d0
        add.l   %d0, %d6

        | r2: phaseB
        move.l  %a2, %d0
        lsr.l   #8, %d0
        lsr.l   #8, %d0
        lsr.l   #8, %d0
        lsl.l   #1, %d0
        move.w  (%a3,%d0:l), %d0
        ext.l   %d0
        add.l   %d0, %d2
        move.w  (%a5,%d0:l), %d0
        ext.l   %d0
        add.l   %d0, %d6

        | r3: phaseB + width
        move.l  %a2, %d0
        add.l   %d5, %d0
        lsr.l   #8, %d0
        lsr.l   #8, %d0
        lsr.l   #8, %d0
        lsl.l   #1, %d0
        move.w  (%a3,%d0:l), %d0
        ext.l   %d0
        add.l   %d0, %d2
        move.w  (%a5,%d0:l), %d0
        ext.l   %d0
        add.l   %d0, %d6

        asr.l   #2, %d2                         | average table i
        asr.l   #2, %d6                         | average table i+1

        | ---- blend: d2 + ((d6 - d2) * fraction) >> 8 ----
        move.l  %d6, %d0
        sub.l   %d2, %d0
        muls.l  %d7, %d0                        | (sum1 - sum0) * fraction
        asr.l   #8, %d0
        add.l   %d2, %d0
        move.l  %d0, %d2

        | ---- advance ----
        add.l   %d3, %d4
        adda.l  %a1, %a2

        | ---- level * env * sample (Q15 chain) ----
        movea.l #SH_BASE+P_LEVEL, %a6
        move.l  (%a6), %d0
        move.l  ST+ST_ENV, %d6
        muls.l  %d0, %d6
        move.l  %d2, %d0
        muls.l  %d6, %d0
        asr.l   #8, %d0
        asr.l   #7, %d0                         | >>15
        move.l  %d0, %d6

        | ---- one-pole LP: lp += (x-lp)>>k, k=1+(127-freq)>>4, clamp 1..8 ----
        | (d1 is the loop counter and must survive: use d0/d2/d6 only)
        move.l  %d6, %d2                        | d2 = x
        move.l  ST+ST_LP, %d0                   | d0 = lp
        sub.l   %d0, %d2                        | d2 = x - lp
        movea.l #SH_BASE+P_FFREQ, %a6
        move.l  (%a6), %d6                      | d6 = freq
        neg.l   %d6
        add.l   #127, %d6                       | d6 = 127 - freq
        asr.l   #4, %d6
        addq.l  #1, %d6                         | d6 = k
        cmp.l   #8, %d6
        ble.s   1f
        moveq   #8, %d6
1:      asr.l   %d6, %d2
        add.l   %d2, %d0                        | lp += diff >> k
        move.l  %d0, ST+ST_LP
        move.l  %d0, %d6                        | d6 = sample

        | ---- write L/R ----
        move.l  %d6, %a0@+
        move.l  %d6, %a0@+

        subq.l  #1, %d1
        bne.w   .Lsample

        | commit phases
        move.l  %d4, ST+ST_PH
        move.l  %a2, %d0
        move.l  %d0, ST+ST_PH2

        | ---- amp env, once per block ----
        movea.l #SH_BASE+P_GATE, %a6
        move.l  (%a6), %d0
        tst.l   %d0
        beq.w   .Lrel
        movea.l #SH_BASE+P_ATK, %a6
        move.l  (%a6), %d0
        move.l  ST+ST_ENV, %d1
        add.l   %d0, %d1
        cmp.l   #32768, %d1
        ble.s   2f
        move.l  #32768, %d1
2:      move.l  %d1, ST+ST_ENV
        bra.w   .Loff
.Lrel:
        movea.l #SH_BASE+P_REL, %a6
        move.l  (%a6), %d0
        move.l  ST+ST_ENV, %d1
        sub.l   %d0, %d1
        bge.s   3f
        moveq   #0, %d1
3:      move.l  %d1, ST+ST_ENV
.Loff:
        move.l  SV_ACCEX(%sp), %d0
        move.l  %d0, %accext01
        move.l  SV_ACC0(%sp), %d0
        move.l  %d0, %acc0
        move.l  SV_MACSR(%sp), %d0
        move.l  %d0, %macsr
        movem.l (%sp), %d0-%d7/%a0-%a6
        lea     80(%sp), %sp
        jmp     0x40003848
