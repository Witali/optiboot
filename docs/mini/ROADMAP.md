# Optiboot Mini improvement plan

Recorded on 2026-11-02. These proposals describe future work; they are not
claims about implemented features or hardware qualification. The public
editions are Mini (`mini`), Middle (`middle`) and Full (`full`).

| Priority | Improvement | Benefit | Completion criteria | Status |
|---|---|---|---|---|
| 1 | Automated build and regression checks | Detect size overflow, protocol regressions and broken device profiles after every change | Pinned tools, all supported profiles, size/layout checks, instruction tests and reviewed build artifacts in CI | Planned |
| 2 | One authoritative microcontroller database | Add or update a device without maintaining parallel geometry tables | Host tools and generated assembly includes use the same validated data; device documentation is generated; existing binaries remain identical | Completed 2026-11-02; see the [database guide](DEVICE_DATABASE.md) |
| 3 | Fuse and lock configuration plans | Match the selected Boot area and protection to the exact MCU | Datasheet-backed masks, signature checks, current-value inspection and a reviewable plan that preserves unrelated bits | Planned |
| 4 | Arduino IDE board profiles | Select the correct edition, upload speed and application size | Board definitions match the generated HEX, Boot geometry and upload protocol; representative IDE/CLI uploads pass | Planned |
| 5 | Interrupted-upload and recovery testing | Establish behavior after truncated packets, delays, reconnects and resets | Reproducible fault sequences exercise every packet boundary and relevant erase/write phase; documented recovery limits | Planned |
| 6 | Hardware qualification of current editions | Validate effects that instruction models cannot establish | Exact image hashes tested on representative boards for cold start, DTR reset, watchdog, UART, Flash/EEPROM timing and power interruption | Planned; software-only work remains the current scope |

## Optional Full-edition feature

Investigate application integrity checking, such as a CRC, before launching
the application. An invalid or unfinished application should leave a usable
upload path. A prototype must define the metadata format and upload-completion
sequence, measure startup cost, and check the 1024-byte budget on every offered
MCU. This is not implemented or promised to fit yet.

Integrity checking can detect an incomplete update. Restoring the previous
application also requires retaining a separate valid copy; a CRC alone does
not provide rollback or atomic updates.

## Implementation order and evidence

Start with the shared database and automated checks, then configuration and
Arduino integration. Keep each change reviewable, retain the original Optiboot
layout and C targets, and preserve the Mini/Middle/Full feature contracts.
Do not add features to the 256-byte edition without measuring every affected
image's size and behavior.

The new editions currently have software evidence. The older Nano hardware
results apply only to the image identified in their report. Hardware work
requires an available board and the user's authorization; this plan does not
start a hardware session.

See the [feature comparison](FEATURES.md),
[edition naming update](EDITION_NAMES_2026-11-02.md) and
[software validation report](UART_VALIDATION_2026-11-01.md).
