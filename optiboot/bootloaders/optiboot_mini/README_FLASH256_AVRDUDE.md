# Flash-only 256-byte edition: AVRDUDE contract

Experimental, assembled and software-modeled only. No physical AVR or running
AVRDUDE binary was exercised in the handoff. ISP recovery is required.

The supported host profile is `-c arduino` (Arduino STK500v1). Plain
`-c stk500v1` and `-c urclock` are not validated/supported for Flash256;
plain STK500v1 may use unsupported UNIVERSAL signature requests.
The original audit used AVRDUDE arduino.c/stk500.c on 2026-10-31.

| Command | Opcode | Payload | Response |
|---|---|---|---|
| GET_SYNC | `30` | None | `14 10` |
| GET_PARAMETER | `41` | One parameter byte | `14 03 10` |
| SET_DEVICE | `42` | 20 ignored bytes | `14 10` |
| SET_DEVICE_EXT | `45` | 5 bytes for version-3 replies | `14 10` |
| ENTER_PROGMODE | `50` | None | `14 10` |
| LOAD_ADDRESS | `55` | Two little-endian Flash word-address bytes | `14 10` |
| PROG_PAGE | `64` | Length, `F`, complete Flash page | `14 10` |
| READ_SIGN | `75` | None | `14 SIG0 SIG1 SIG2 10` |
| LEAVE_PROGMODE | `51` | None | `14 10`, then 16 ms watchdog reset |

All packets end in `CRC_EOP=20`, a terminator, not a computed CRC.
No GET_SIGN_ON, READ_PAGE, UNIVERSAL, EEPROM, or fuse programming is supplied.
`-V` disables unsupported readback verification. `-D` prevents unsupported
host-side chip erase and implies `-A` (retain trailing FF bytes); `-A` can also
be explicit.

Flash256 ignores transmitted PROG_PAGE length and receives exactly one 64/128-
byte physical page. A short final host block can hang or time out. The converter
pads touched pages with FF, rejects boot overlap, and requires a complete
application image: padding erases prior data in the rest of a touched page.

```sh
python3 flash256/prepare_avrdude_hex.py --mcu atmega8 --input firmware.hex --output firmware.padded.hex
avrdude -c arduino -p m8 -P COM5 -b 115200 -D -V -U flash:w:firmware.padded.hex:i
python3 build_flash256.py --all --f-cpu 16000000 --baud 115200
python3 -m unittest mini_tests.test_flash256 mini_tests.test_flash256_avrdude -v
```

Use the correct port, device, and baud; 8 MHz builds use 38400 in these examples.
ACKs report completion without independent readback; ISP verification is
preferable. `-F` is neither required nor recommended. Match BOOTSZ/BOOTRST.
Targets: ATmega8/8A, 88/88P, 8515, 8535, 16, 162, 164A/P/PA, 168/168P.
This branch shares the same assembly source with Compact/Full; no replacement
of those editions occurs. Actual UART/SPM/fuse timing remains untested.
