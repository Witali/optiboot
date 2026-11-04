# ATmega328PB Nano USB hardware tests

This is a repeatable bench test for **Optiboot Mini on an ATmega328PB Nano,
16 MHz, USART0 at 115200 baud**, with the edition-specific Boot layout below.
It uses real AVRDUDE transfers and a serial protocol client. It does not
simulate a chip or qualify the other device profiles.

The runner has three explicit, pinned editions:

| Parameter | Firmware | Boot BIN SHA-256 |
|---|---|---|
| `-Edition basic` (default) | Original Basic image qualified on 2026-10-30 | `149ebc0347815b42daaa20defce83342462306e9ddd3f15c63eeb59baafd70d1` |
| `-Edition middle` | Current 512-byte Middle image, 510 bytes of code/footer | `156d3701c01e5a9f5008b371c08e4753b7d7200e1535b1c776755040723a99c1` |
| `-Edition full` | Current 1024-byte Full image, 635 bytes of code/footer | `6a16bbe0776d704e4c9ab7651961bd35b02efe68809a7492090232014d5d82ef` |

| Edition | Boot bytes / start | Application bytes | Scratch page | Fuses LF / HF / EF |
|---|---|---|---|---|
| Basic, Middle | 512 / `0x7E00` | 32256 | `0x7D80` | `FF / DE / FD` |
| Full | 1024 / `0x7C00` | 31744 | `0x7B80` | `FF / DC / FD` |

Each edition is checked against a fresh read of the installed Boot section,
signature `1E9516`, the matching fuses, and lock byte `CF`. Middle and Full require
verified, current-board ISP readouts before any serial test writes. Middle's
`UNIVERSAL` handler returns zero for fuse/lock queries; Full returns the actual
four bytes. Actual configuration is also read directly by the diagnostic application.
Hardware results for one edition or board do not qualify another automatically.
The pinned Full build uses MCUSR parity explicitly, as recorded in its build manifest.

## Requirements

- Windows with PowerShell 7.2 or later.
- AVRDUDE 8 with the `m328pb` and `arduino` definitions.
- AVR-GCC, `avr-objcopy`, and `avr-objdump`, either on PATH or in WSL.
- A Nano connected by its own USB cable, with the correct serial driver.
  Close other applications using its COM port.

The standalone C probes use the ATmega328P register definitions shared by
this ATmega328PB configuration. The diagnostics obtain the actual device
signature from silicon. No Arduino core, Python package or GUI is required.

## Run

From the repository root, set the COM port and the installed AVRDUDE path.
For the Arduino-packaged version used in the recorded run:

```powershell
$avrTool = Join-Path $env:LOCALAPPDATA 'Arduino15\packages\arduino\tools\avrdude\8.0.0-arduino1'
$testArgs = @{
    Port = 'COM3'
    AvrdudePath = Join-Path $avrTool 'bin\avrdude.exe'
    UseWslToolchain = $true
}

# Build the probes and make verified backups, without writing test data.
.\scripts\hardware\nano_usb\test_nano_usb.ps1 @testArgs

# Run the complete bench test, including the physical power-cycle step.
.\scripts\hardware\nano_usb\test_nano_usb.ps1 @testArgs -Run -ColdStart
```

For Middle or Full, first install the exact image using ISP and verify the complete
readback. Preserve that private installation directory, then run:

```powershell
.\scripts\hardware\nano_usb\test_nano_usb.ps1 @testArgs -Edition middle `
    -IspBackupDirectory 'C:\path\to\verified-isp-installation' -Run

# Use the Full installation's own fresh ISP directory for the 1024-byte image.
.\scripts\hardware\nano_usb\test_nano_usb.ps1 @testArgs -Edition full `
    -IspBackupDirectory 'C:\path\to\verified-full-isp-installation' -Run -ColdStart
```

To repeat only the physical cold-start phase after a completed bench run, use
the same arguments with `-ColdStartOnly -Run` and a new output directory. This
implies `-ColdStart`; it cannot be combined with `-RestoreFromDirectory`. The
focused mode retains the verified ISP/serial preflight, watchdog-probe upload
and handoff check, power-cycle evidence, final direct diagnostics, and complete
application/EEPROM restoration. It skips the full memory/raw protocol/appSPM
phases and the 50 watchdog, 20 DTR, BREAK and reconnect stress cases.

The ISP directory must contain `after-flash.bin` (32768 bytes),
`after-eeprom.bin` (1024 bytes), and the actual `after-signature.bin`,
`after-lfuse.bin`, `after-hfuse.bin`, `after-efuse.bin`, `after-lock.bin` readouts.
Its `isp-result.json` must record `isp_programming`, `complete_flash_readback`
and `eeprom_readback` as `PASS`, and `boot_sha256` as the selected edition's pinned hash.
Before test writes, the serial Flash/EEPROM/signature backups must match those
ISP readouts exactly. Both copies must remain private. An existing test backup
directory is never overwritten.

Middle checks `GET_SIGN_ON` as an ACK-only compatibility operation, plus all
three signature bytes through `UNIVERSAL 30 00 index 00`. It does not interpret
unsupported fuse/lock queries as real fuse values. The final diagnostic application
rechecks actual signature/fuses/locks after protocol and reset tests, before the
original application and EEPROM are restored.

Full checks the `AVR STK` sign-on string, all three `UNIVERSAL` signature bytes,
and actual low/extended/high fuses and lock byte through `UNIVERSAL`. Its
`SET_PARAMETER` compatibility handler must consume two payload bytes, including
payload bytes equal to EOP (`0x20`), acknowledge without changing fixed version
parameters, and reject malformed or incomplete packets with watchdog recovery.
The final direct application diagnostics also run for Full.

Middle and Full also run `app_spm_probe.c`, which invokes the matching Boot application
SPM ABI to erase, write and restore the scratch page listed above. The selected
Boot size determines the call entry: `0x7E02` for Middle, `0x7C02` for Full. Only the
reviewed erase/fill/write operations are used. Protected Boot-address calls must
return; the host verifies complete Flash and EEPROM afterward, including the
restored scratch page and unchanged Boot bytes. With lock byte `CF`, this checks
the protected configuration and does not isolate software protection from
hardware lock protection.
The physical probe keeps interrupts disabled and waits for EEPROM completion
for both ABIs. Full's CLI/SREG restoration and opcode whitelist have separate
instruction-model coverage; asynchronous interrupts are not simulated. The
physical probe never calls lock-bit programming (`0x09`) or RWW-only (`0x11`).

The runner finds `../etc/avrdude.conf` beside the executable when available.
Use `-AvrdudeConfig <absolute-path>` to override it. Omit
`-UseWslToolchain` when the AVR build tools are on the Windows PATH.

Each invocation creates a **new** output directory under the checkout's
ignored `.worktree/` directory. `-OutputDirectory` can select a new directory
there or outside the checkout. An existing output directory is refused.
Output contains the board's current application and EEPROM: keep it local
and do not commit or publish it.

When `READY_FOR_POWER_CYCLE` appears, unplug **all** power to the Nano,
including any ISP power, then reconnect only its USB cable to the same
computer USB port so that the COM-port assignment stays the same. The test waits
for the port to disappear and return, then queries the running application.
Before this step an application command clears and verifies an entry record
and uptime counter at EEPROM addresses `1014..1023`, then stops updating
them in the running application. The serial handle stays open until physical
USB removal, so closing it cannot reset the armed application first.
The next application invocation records its handoff state and advances a
500 ms counter. Later invocations preserve that evidence.
After USB returns, the host waits four seconds before opening the port. All
three editions accept at least three saved ticks as an autonomous-uptime proof.
Middle and the pinned Full additionally accept at least one tick when the first recorded reset
cause contains PORF and contains neither EXTRF nor WDRF. That alternative
establishes power-on application entry and at least 500 ms of first-invocation
execution; it does not establish 1.5 seconds or four uninterrupted seconds.
All paths require the cleared-and-rearmed `STAR` record, zero initial `r1`,
the edition's expected MCUSR state, and a disabled watchdog. Basic expects
MCUSR zero. Middle and the pinned Full preserve the reset cause, clearing WDRF only when the
recorded cause contains EXTRF. The observation JSON records the proof kind.
The saved record distinguishes first-invocation execution from later resets.
It does not directly timestamp that invocation relative to the host opening
the port. The cause and timing of subsequent resets are not measured.
The complete original EEPROM is restored afterward.

The general three-tick path does not require PORF: a bootloader can wait in UART
mode after an external-reset indication, then enter the application through its
watchdog. The lower-tick Middle/Full alternative specifically requires PORF.
A 120-second timeout applies to each port transition.

For an unattended run, omit `-ColdStart`. The JSON result explicitly records
that physical cold start was not requested. That run does not cover power-on
behavior. Creating `cancel-cold-start.txt` in the output directory cancels a
pending power-cycle step and enters restoration.

Run `test_cold_evidence.ps1` to check edition geometry/configuration and cold-start
evidence acceptance/rejection without any hardware. It extracts only the pure helpers through the PowerShell AST and does
not execute the hardware runner.

## Coverage

- Read and independently verify complete Flash, EEPROM, signature, fuses
  and lock bits before the first write.
- Write and verify all **32,256 (Basic/Middle) or 31,744 (Full) application bytes**, including the final
  page before Boot, and all **1,024 EEPROM bytes** using AVRDUDE.
- Run direct fuse/lock diagnostics from the application; require three stable
  reports and confirm blocked application reads of the boot section.
- Check STK500v1 sync, sign-on, version, signature, 256-byte reads, the legacy
  zero-length read encoding, and reads across the application/Boot boundary.
- For Full, check two-byte `SET_PARAMETER` framing, unchanged fixed parameters,
  and real `UNIVERSAL` signature/fuse/lock readouts.
- Check EEPROM writes of every size 1 through 16 at its upper boundary.
- Check a two-byte Flash write, including the documented erasure of the
  unspecified bytes in that page, then restore the complete test page.
- Reject unknown memory types, invalid lengths, unaligned writes,
  overflowing addresses, out-of-range reads/writes, invalid terminators and
  incomplete Flash/EEPROM packets. Verify the complete test memories again.
- Reject a boot-page programming packet whose payload is identical to the
  installed page. Verify that the boot section is unchanged. The test does
  not bypass the firmware guard to destructively probe hardware lock bits.
- Check the unsupported UNIVERSAL zero response and the existing no-op
  Chip Erase acknowledgement.
- Observe initial `r1`, edition-specific `MCUSR`, reset reason in `r2`, and disabled watchdog
  before the application deliberately enables it. The watchdog probe does
  **not** disable the watchdog on startup.
- Perform **50 application-triggered 15 ms watchdog resets**,
  **20 DTR reset / sync / leave cycles**, UART echo and BREAK recovery,
  and three consecutive real AVRDUDE sessions.
- Optionally verify autonomous startup after a physical power cycle, then restore the original
  application and EEPROM and verify **all 32,768 Flash bytes**, EEPROM,
  signature, fuses and lock bits against the initial backup.

`usb-test-result.json` records individual results, restoration status and
cold-start coverage, edition and firmware source revision. The first application
handoff and first watchdog restart retain their raw observations in separate
JSON files. Ordinary watchdog cycles can retain a sticky external-reset flag;
they do not establish behavior for a pure WDRF-only reset cause. The watchdog restart time is observed by the host and
includes USB and host scheduling delays; it is not an oscillator measurement.

## Restoration and interruption recovery

Once test writes begin, the runner attempts restoration in `finally`, even
when a test fails. It never changes fuses or lock bits and does not include
the boot section in its normal Flash write images. Restoration requires a
connected, responsive board. Keep the backup directory if a cable is removed
or the process is interrupted.

To restore from that original directory after reconnecting the same board:

```powershell
.\scripts\hardware\nano_usb\test_nano_usb.ps1 @testArgs `
    -RestoreFromDirectory 'C:\path\to\the\saved\output' -Run
```

Include the matching `-Edition middle` or `-Edition full` when recovering its test. The saved output records
the original ISP evidence directory; keep it available, or pass the same
`-IspBackupDirectory` explicitly. Recovery checks the currently installed edition's
Boot hash before restoring application bytes.

This checks the device configuration, restores the saved application and
EEPROM, and verifies the complete memories. It preserves the `before-*`
backup files. Do not start a new test to recover a board whose original
application has not yet been restored.

The suite is functional validation of one configuration. It does not measure
voltage or temperature margins, oscillator accuracy, Flash endurance,
power-loss atomicity during erase/write, or other MCU variants.
