# Expanded Optiboot Mini handoff and import validation

Date: 2026-10-30. This update extends the existing Mini feature branch from
15 profiles to **38: 34 ATmega and four Virtual Boot ATtiny**.

## Source and integration

Source package: `Optiboot_Mini_COMPLETE_AGENT_HANDOFF_2026-10-30.zip`.
SHA-256:

```text
a27cbac1221a2bc47101e42c7ed1d065d1b59080b232674de3cf05135d51756e
```

The prior repository state is commit `70daf9d` on
`feature/optiboot-mini-update-2026-10-30`. The source of truth in the package is
`optiboot/bootloaders/optiboot/`, containing 83 files. The full package patch
targets upstream commit `e363ecbe2b6542b5db5b4209589f274c87d833a7` and changes
only `Makefile.custom` among pre-existing upstream files.

For this already integrated checkout, both incremental patches were checked
and applied in order: `optiboot-mini-expansion-from-prior-handoff.patch`, then
`optiboot-mini-softuart-from-expanded.patch`. Neither rejected hunks nor a
three-way application was needed. The existing Mini include blocks and local
Clang/GCC relocation handling were preserved.

All firmware source, generated device definitions, UART modules, tests and Tiny
utilities remain in their original relative source paths. The existing main
Makefile, C implementation, protocol headers, stock firmware, other bootloader
directories and ATmega328P research tree are unchanged. No upstream directory
was moved or flattened. There is no new overlay directory.

Package-only history archives, distribution patches, helper scripts and
prebuilt objects were used as references and are not copied into the source
checkout. Documentation and the new verification matrix are placed in the
existing `docs/mini/` directory. Generated build products remain ignored.

## Instructions retained from the agent handoff

The package entry points, complete context, original and software-UART
handoffs, update scope, release/history manifests, latest build matrix,
technical guides and verification reports were reviewed. Their current
requirements are:

- Continue from the current source tree; historical snapshots are for tracing
  regressions and must not replace current sources.
- Keep the standard Uno configuration: ATmega328P, 16 MHz, 115200 baud. Its
  frozen 512-byte image must remain byte-identical.
- Preserve the supported STK500v1 subset, Flash and EEPROM reads/writes,
  signature and read-only fuse/lock operations, packet checks, boot-region
  checks and watchdog behavior. Do not remove features merely to reduce size.
- Use 512-byte images where practical for small classic ATmega. Use the
  appropriate 1024-byte region for larger ATmega and experimental ATtiny;
  do not impose a universal 512-byte limit.
- Retain separate legacy, modern and Tiny UART implementations. ATmega2560/2561
  require four Flash banks and `UNIVERSAL 0x4D` address-bank handling.
- ATtiny Virtual Boot requires an ISP seed, self-programming permission and
  relocated RESET/EE_RDY vectors. ATtiny1634 erases four physical 32-byte pages
  as a group, requiring complete 128-byte Flash transfers. Its dedicated host
  uploader performs grouped writes and verification.
- ATtiny84/85 use software UART, defaulting to 8 MHz internal RC / 19200 baud;
  their 582-byte code is allowed a 1024-byte reserved region. Clock/fuse
  configuration and calibration remain external responsibilities.
- Keep repository code, comments, filenames, messages and documentation in
  English. Old handoff notices describing 36 profiles or unimplemented
  ATtiny84/85 are historical and are superseded by the current 38-profile tree.
- Rerun the entire software suite before claiming it passed. Previous package
  reports contain interrupted full-suite runs; they do not establish a pass.
- Treat all ports as experimental until physical-device validation. Do not
  report emulator results as real MCU, UART or AVRDUDE measurements.

The [Virtual Boot guide](VIRTUAL_BOOT.md) preserves installation, transfer-size,
software-UART, vector-patching and recovery details in English.

## Local integration adjustments

The prior relocation fix now selects linker emulations for the expanded CPU
families: AVR25 for ATtiny84/85/841, AVR35 for ATtiny1634 and AVR6 for the
256-KiB ATmega parts. Existing AVR4/5/51 choices remain. Linking stays at
section address zero without relaxation; Intel HEX supplies the boot address.
Unresolved relocations are rejected before binary extraction.

The all-device test now uses 8 MHz for ATtiny84/85, matching their internal-RC
defaults, and 12 MHz for ATtiny1634. Its firmware, layout and HEX assertions are
retained. ATtiny84/85 at 16 MHz external clock are exercised separately by the
software-UART tests.

The current ATmega1284/1284P code is 592 bytes, down from the earlier 15-profile
release's 608 bytes. Current documentation uses the new build results while
the [original import report](IMPORT_2026-10-30.md) retains its historical scope.

Source review also found that software UART refreshes the watchdog while idle,
so it does not implement the hardware-UART receiver's inactivity timeout.
An inaccurate source comment implying timeout after malformed framing was
corrected; no instruction or firmware byte was changed. The Virtual Boot guide
records the behavior as an outstanding limitation of the imported ATtiny84/85
ports rather than treating it as equivalent watchdog behavior.

## Validation performed on this checkout

| Check | Result |
|---|---|
| Package SHA index | All 351 indexed files matched before import. |
| Full package patch | Original upstream `Makefile.custom` fixture; clean apply/reverse; all 83 resulting files matched the package. |
| Incremental integration | Both patches passed `git apply --check` and `git apply --whitespace=error` against the local checkout. |
| Full software suite | `make mini_test`: **70 tests passed in one run**, 67.126 seconds. |
| Default firmware matrix | **38/38** BIN and HEX pairs matched the handoff byte for byte; every generated manifest field matched its packaged value. |
| Virtual Boot ISP seeds | **4/4** seed HEX files matched the handoff byte for byte. |
| Stock Make integration | `make mini` plus explicit ATmega2560, ATtiny84/85/841 and 12-MHz ATtiny1634 targets built successfully. |
| Frozen standalone 328P | `make mini328_check` reproduced the reference BIN hash. |
| Repository checks | Whitespace, English-language content, local documentation links and staged sensitive-content checks passed. |

The [38-profile validation matrix](EXPANDED_BUILD_MATRIX_2026-10-30.json)
records clocks, UART rates, memory geometry, code/image sizes, hashes and the
four seed hashes without machine-specific paths. Builds and tests used the
installed Ubuntu WSL AVR tools against the full local Optiboot checkout.

The frozen ATmega328P BIN remains:

```text
be531a3f0b7294c6e9f00f4d02a8c5e7ff28d8fb2b7c90cb6501d0294cfae00b
```

## Remaining work

Physical-device programming and recovery, real AVRDUDE interoperability,
oscillator/OSCCAL behavior over voltage and temperature, UART waveforms,
watchdog timing, CCP, SELFPRGEN, SPM/EEPROM latency, grouped erase, interrupts,
application dispatch and power-loss recovery still require hardware testing.
The software-UART inactivity policy also needs explicit review before use.
Virtual Boot can lose UART recovery if RESET-page programming is interrupted;
keep ISP access. ATtiny44/45 remain future work.

This update prepares the feature branch for review. It does not establish a
production release or modify the upstream `master` branch.
