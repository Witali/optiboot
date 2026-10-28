# Page-header hardening within the existing boot section

## Preparatory counter refactor

The audited baseline used 510 instruction bytes plus two version bytes, filling
the 512-byte boot section. Its BIN SHA256 was
`29fe3aa03cc412568160d1990cefa12f7674f243f8c3d6336bdc09fbe79fd642`.

The first change represents page lengths as the zero-based final byte index in
r24. Flash programming shifts that index into a zero-based final word index.
Loops use SUBI/BRCC to include index zero; the EEPROM end-address check can use
the offset directly. Flash and EEPROM write-size bounds still reject their old
invalid sizes without separate zero-count tests.

| Step | Instructions | Version | Occupied | BIN length |
|---|---:|---:|---:|---:|
| Audited baseline | 510 | 2 | 512 | 512 |
| Counter-only refactor | 504 | 2 | 506 | 512 |

The six recovered bytes are FF padding. No capability is removed. At this
preparatory step, the old high-length/type behavior remains unchanged; the
following implementation step will use the recovered bytes for validation.

All five existing regression suites passed against the refactored BIN, including
the 556 upstream differential transactions, full EEPROM round trips, fuse/lock
queries, Flash alignment checks and the old documented protocol-limit behavior.
The counter-only BIN SHA256 is
`37eeb2872e39f548f3e0139c589f769332fa612cb9a2a5d8629e7222e7a429b5`.

The source and current BIN/HEX/object artifacts are updated together. Original
source/image/object snapshots remain in history and the stage archives. The
import manifest records both the handoff hashes and current working versions.
These measurements and tests use software tools; physical-board testing remains
pending.
