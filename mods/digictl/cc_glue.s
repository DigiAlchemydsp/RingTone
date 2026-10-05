| Digi FX MIDI CC entry (Digitone mk1/Keys, OS 1.43).
|
| Every incoming MIDI Control Change reaches the central CC router at
| 0x400ED94E, whose first two instructions are
|     0x400ED94E  lea   sp@(-24),sp
|     0x400ED952  moveq #8,d0
| mod.json replaces those 6 bytes with `jsr digictl_cc_disp`. On entry the
| stock arguments are on our caller's stack:
|     sp@(0)  = return address (kept; stock will rts to it)
|     sp@(4)  = track (0..7, or 8 = global)
|     sp@(8)  = CC number
|     sp@(12) = CC value
| We read the CC number/value, call digictl_cc_apply (C), then execute the two
| displaced instructions and jump into the stock router at 0x400ED954. CC
| numbers we do not own are left to stock (which ignores the free CCs we use).
        .section .run, "ax"
        .balign 2
        .globl  digictl_cc_disp
digictl_cc_disp:
        move.l  %sp@(8), %d0                | CC number
        move.l  %sp@(12), %d1               | CC value
        movel   %d1, %sp@-                  | push value
        movel   %d0, %sp@-                  | push cc
        jsr     digictl_cc_apply            | digictl.c
        addq.l  #8, %sp
        lea     -24(%sp), %sp               | displaced instruction 1
        moveq   #8, %d0                     | displaced instruction 2
        jmp     0x400ED954                  | stock router continues
