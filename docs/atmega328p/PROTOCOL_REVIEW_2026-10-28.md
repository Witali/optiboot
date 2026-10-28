# STK500v1 protocol review: declared Arduino bootloader subset

This is the pre-hardening review and its original observations. The subsequent
[header hardening](HEADER_HARDENING_2026-10-28.md) fixes the length/type issues
reported below while keeping the same 512-byte image size. The original JSON
remains before-change evidence; current results are linked from the follow-up.

**Date:** October 28, 2026.
**Firmware baseline:** `891169f84898b7a73bc55f21a5b17f5b1642fa33`.
**Source:** `optiboot_328_verified.S`.
**BIN SHA256:** `29fe3aa03cc412568160d1990cefa12f7674f243f8c3d6336bdc09fbe79fd642`.

## Result

The declared ATmega328P Arduino upload subset passed the software checks:
all five existing regression suites and 44 additional supported-profile checks.
No failure was found in those tested valid exchanges. Missing programmer
features are recorded separately; their absence does not establish that the
implemented bootloader functions fail.

The evidence does not establish full AVR061 compliance or physical-hardware
reliability. Malformed/out-of-profile packets expose two memory-changing
hardening issues: ignored high length bits can turn an incomplete oversized
declaration into a short write, and an undefined memory type selects Flash.
Neither packet is a valid request in the declared Arduino profile.

No firmware instructions or images were changed by this review.

## Primary references and interpretation

1. [Microchip/Atmel AVR061, revision 2525B, April 2003](https://ww1.microchip.com/downloads/en/AppNotes/doc2525.pdf).
   The retrieved 31-page PDF has SHA256
   `6731b56866e08716136fc2843d1ddc98c2a9d689b660e023d523684f892cae9e`.
2. [AVRDUDE STK500 driver at commit 9aa44d08cb207a80a5d1005ead61142d21fb50de](https://github.com/avrdudes/avrdude/blob/9aa44d08cb207a80a5d1005ead61142d21fb50de/src/stk500.c).
3. [AVRDUDE Arduino driver at the same commit](https://github.com/avrdudes/avrdude/blob/9aa44d08cb207a80a5d1005ead61142d21fb50de/src/arduino.c).

AVR061 is the STK500v1 reference. Its response definitions are on page 2;
sign-on and synchronization on page 3; parameters on page 4; setup and address
loading on pages 6-8; page programming/reading on pages 11/14; and UNIVERSAL on
page 16. Page lengths use both header bytes, with blocks up to 256 bytes and
memory types E/F. The sign-on payload is `AVR STK`; malformed termination and
unknown commands have defined responses. Page operations require LOAD_ADDRESS
before each operation. These are protocol reference points, not a requirement
to add every programmer feature to this fixed-target bootloader.

The reviewed AVRDUDE code provides the practical client profile:

- `stk500_setup()` changes a bootloader's one-byte EEPROM page size to 16.
- `set_memchr_a_div()` uses word addressing for classic AVR bootloaders,
  including EEPROM; a generic STK500 programmer can use a different convention.
- `stk500_paged_write()` and `stk500_paged_load()` send LOAD_ADDRESS before
  each block, then a two-byte length and memory type.
- Reported software 8.3 selects four extended parameters plus the count byte:
  five bytes after SET_DEVICE_EXT, before EOP.
- The Arduino driver reads the signature with READ_SIGN, rather than depending
  on a UNIVERSAL signature-read implementation.

These source-level observations do not constitute a test with a running AVRDUDE
executable. AVRDUDE was not installed in the available WSL environment.

## Supported-profile checks

The [audit program](../../scripts/atmega328p/audit_protocol.py) executes the
assembled image through the supplied instruction/peripheral model. Its
[complete JSON observations](PROTOCOL_AUDIT_RESULTS_2026-10-28.json) separate
supported-profile assertions from diagnostic boundary probes.

| Area | Observed result |
|---|---|
| GET_SYNC and ENTER | Expected `14 10` framing in the tested setup sequence. |
| GET_PARAMETER | Software major/minor return 8/3 with correct framing. Other settings are not part of the version-query contract. |
| SET_DEVICE / SET_DEVICE_EXT | Consumes the 20-byte base form and five-byte extended form used by the reviewed current client; the following command remains synchronized. |
| SET_PARAMETER | Consumes both fields and EOP as documented for this bootloader's no-op implementation. No parameter-setting capability is claimed. |
| LOAD_ADDRESS | Word-to-byte conversion works for the tested Flash and EEPROM blocks. |
| Flash PROG_PAGE / READ_PAGE | A full last application page at `0x7D80` round-trips, embedded command/EOP bytes remain payload, and the boot image is unchanged. Existing suites cover 25 aligned length/address combinations and reject five unaligned starts before SPM. |
| EEPROM PROG_PAGE / READ_PAGE | The final 16-byte block at `0x3F0` round-trips. A valid length `0x0100` reads all 256 bytes; the ignored high-byte issue does not break this particular valid case. Existing suites cover the full 1 KiB, short blocks and negative cases. |
| UNIVERSAL supported reads | All four supported low/high/extended fuse and lock query forms have correct result framing in the model. |
| READ_SIGN | Returns `14 1E 95 0F 10`. |
| LEAVE | Returns `14 10` and configures the short watchdog. Actual elapsed reset time is not modeled. |
| Transport | Concatenated complete commands work. All 20 two-piece split positions of a 16-byte EEPROM write packet preserve parsing and cause no EEPROM writes before EOP. |

The 44 checks include the 20 fragmentation cases; they are not 44 independent
proofs of all possible packet sequences. The existing suites also passed their
556 upstream differential transactions and EEPROM/fuse/Flash regressions.

The address register is not advanced globally after page operations. This was
not classified as a defect: AVR061 page 8 requires LOAD_ADDRESS before page
operations, and the reviewed host sends it for each block. CHECK_AUTOINC concerns
other legacy primitives; its ACK must not be used to infer support for those
unimplemented primitives.

## Unsupported capabilities

These observations describe scope, not failures of the valid upload checks:

| Capability | Current behavior | Consequence |
|---|---|---|
| GET_SIGN_ON | `31 20` returns `14 10`, without a string. | Clients requiring sign-on are outside the declared profile. |
| Single-byte/word memory primitives | For example, READ_DATA `71 20` returns only ACK. | Use supported page operations; the full programmer command set is not provided. |
| Arbitrary UNIVERSAL / signature | Signature query `56 30 00 00 00 20` returns zero; only four fuse/lock query forms are implemented. | Arduino READ_SIGN works; generic ISP expectations do not apply. |
| Global Chip Erase / fuse-lock writes | No implementation; Chip Erase can ACK without modifying memory. | Do not request explicit global erase or fuse/lock programming. Normal Flash writes erase the selected pages themselves. |
| Adjustable programmer parameters | Unsupported selector `7F` returns `03/OK`; SET_PARAMETER changes no configuration. | Version-query/packet parsing works, but general settings are not available. |

An ACK on an unsupported capability must not be interpreted as evidence that
the requested operation actually occurred. More explicit rejection would improve
client diagnostics without requiring implementation of the missing feature.

## Packet boundaries and error policy

### 1. Oversized length can cause a premature Flash write

Source: `read_length` at line 328 and `command_write` at line 229 of the audited
assembly. The first size byte is discarded.

Probe:

```text
64 01 02 46 AA BB 20
```

The header declares 258 bytes, above the protocol block limit and outside this
bootloader's 2..128-byte Flash-write range. Only two data bytes and a following
`20` have arrived. The image nevertheless returns `14 10` and modifies application
Flash, because it treats the declaration as length two. This is a malformed
packet handling issue, not evidence that a normal supported two-byte write fails.
The corresponding oversized read `74 01 02 45 20` returns only two data bytes.

Recommended hardening: validate the complete size before accepting payload.
Preserve the explicit valid `01 00` representation for 256-byte reads. The
response/recovery policy for unsupported sizes should be documented.

### 2. Undefined memory type can write Flash

Source: the type checks in `command_read` at line 148 and `command_write`.

Probe:

```text
64 00 02 58 AA BB 20
```

Type `58` is X, outside E/F. The image returns `14 10` and changes application
Flash. Valid E/F operations passed; the issue is accepting an undeclared type
as Flash. Explicit type validation would prevent that fallback.

### 3. Extended-device parameter versions

`45 05 10 D7 A0 00 20` passes. The shorter
`45 04 10 D7 A0 20` produces no reply and waits for another byte, because
`command_discard` at line 132 always consumes five bytes for this command.

AVR061 page 6 is internally inconsistent: the syntax and count explanation show
the shorter form, while Table 6 also lists ResetDisable. The table was visually
checked. Current AVRDUDE explicitly chooses the longer form for reported 8.3,
so this is a compatibility boundary, not a demonstrated current-client failure.
If older/other clients are a goal, honor the declared count or document the
accepted fixed version.

### 4. Error responses and recovery

Unknown command `7F 20` gets ACK. Bad EOP `30 00` emits no NOSYNC and enters
the short-WDT error loop (`verify_eop`, line 334; `protocol_error`, line 321).
This is an Optiboot-style recovery policy differing from the general programmer
responses. The model identifies entry into the abort loop; it does not reproduce
physical watchdog expiration or host reset/reconnect behavior.

## Reproduction and practical conclusion

The unchanged assembly was rebuilt using the available WSL LLVM/AVR tools.
The result remains 510 instruction bytes plus two version bytes, and its BIN
hash matches the audited supplied image. All five existing suites passed.

```sh
make -C optiboot/bootloaders/optiboot_328p test
python scripts/atmega328p/audit_protocol.py \
  --firmware optiboot/bootloaders/optiboot_328p/build/optiboot_328_verified.bin \
  --output docs/atmega328p/PROTOCOL_AUDIT_RESULTS_2026-10-28.json
```

The audit exits unsuccessfully if a supported-profile assertion fails. A zero
exit status reports that those assertions passed, not full AVR061 compliance;
the JSON must still be read for boundary observations.

The evidence supports the implemented Arduino upload subset in the supplied
software model. It does not prove behavior for every possible stream or on a
physical board. The next implementation priority is validation of complete
lengths and memory types, rather than adding optional commands. The current
512-byte image has no spare space, so any such change requires size-aware work
and a fresh build/regression cycle.
