| Digi Filter (Digitone mk1/Keys, OS 1.43): the raw site entry point.
|
| The render ISR (0x4009d100) computes, just before it calls the voice mix
| 0x40096e14, the output half it will write:
|        0x4009e138  movel %fp@(-104),%d0
|        0x4009e13c  lsll  #8,%d0
|        0x4009e13e  addil #0x80001a00,%d0     <- our jsr site (6 bytes)
|        0x4009e144  movel %d0,%sp@-
|        0x4009e146  jsr   0x40096e14
| mod.json replaces the addil with a jsr here. We do the displaced add, filter
| the eight FM voices in 0x80004110 (the second CPU's output, before the mix),
| then return; the render's own movel/jsr still run. All registers are kept so
| the render sees exactly what the stock path left in d0.
        .section .run, "ax"
        .balign 2
        .globl  digifilter_disp
digifilter_disp:
        add.l   #0x80001a00, %d0                | the displaced instruction
        lea     -64(%sp), %sp
        movem.l %d0-%d7/%a0-%a6, (%sp)          | 15 registers, 60 bytes
        jsr     digifilter_run                  | filter.c
        movem.l (%sp), %d0-%d7/%a0-%a6
        lea     64(%sp), %sp
        rts
