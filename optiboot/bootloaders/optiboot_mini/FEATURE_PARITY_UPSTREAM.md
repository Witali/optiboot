# Upstream Optiboot v8.3 feature comparison (2026-10-30)

Historical audit: the statements below about missing 512-byte application SPM
predate the later compact ABI. Current Middle supports that ABI on 21 ATmega;
see README_DUAL_EDITIONS.md. This record preserves the earlier comparison.

Audited against the upstream `Optiboot/optiboot` master version of
`optiboot/bootloaders/optiboot/optiboot.c` (Git blob SHA
`d7fba90a02616f095ec733ac4c434b4d42db58a6`) and its `Makefile`.

Source: https://github.com/Optiboot/optiboot/blob/master/optiboot/bootloaders/optiboot/optiboot.c

**Optiboot Mini is a compatible STK500v1 subset, not a drop-in replacement for
all build-time features of upstream Optiboot.** Its version reply is 8.3 for
protocol interoperability but does not imply full upstream feature parity.

| Capability | Upstream Optiboot 8.3 | Optiboot Mini |
| --- | --- | --- |
| UART STK500v1 sync, page flash R/W, signature `0x75` | Yes | Yes |
| Chip-erase acknowledgement without real bulk erase | Yes | Yes |
| EEPROM read/write | Optional `SUPPORT_EEPROM` or `BIGBOOT` | Built-in |
| `STK_UNIVERSAL` fuse/lock read | Generic zero reply | Supported in default/full Mini; excluded from compact 512B dual-signature build |
| `STK_UNIVERSAL` signature `0x30` | Generic zero reply | Optional dual-signature build |
| Application-callable bootloader SPM service | Yes by default (`APP_NOSPM=0`) | **Now supported with `--app-spm` (1024B hardware Boot); not available in 512B and Virtual Boot images** |
| Startup/activity LED (`LED_START_FLASHES`, etc.) | Configurable; upstream Makefile defaults to 3 flashes | **Not implemented** |
| RS-485 direction control | Optional | **Not implemented** |
| UART number (`UART=0/1/...`) | Configurable | Per-device fixed profile only |
| User-configurable watchdog timeout (`WDTTIME`) | Yes | Fixed 1 second |
| Reset-cause options (`START_APP_ON_EXTR`, `NO_START_APP_ON_POR`) | Yes | Fixed reset policy |
| `OSCCAL_VALUE` calibration override | Optional | **Not implemented** |
| Virtual Boot app-vector patch/verify inside bootloader | Available | Uses separate `tiny/patch_vectors.py` tool instead |
| Software UART | Optional AVR305-based | Dedicated bit-banged ATtiny84/85 driver |
| BIGBOOT build metadata | Optional | Absent; manifest JSON is generated on host |

The default `make mini` and explicit `mini328_sig512` targets **do not** silently
accept official options that would have no effect: `Makefile.mini.inc` now fails
with a message naming unsupported user options. Use the original upstream
`optiboot.c` build targets if such features are required. We deliberately do
not add a broken application-callable SPM stub to our 512B images. Use
`make mini_spm` or `--app-spm` for a 1024-byte image with this service.

## Project clock and speed policy

- The builder rejects actual CPU clocks below **8 MHz**, even with override
  flags. `F_CPU` must equal the clock after CLKDIV8 and CLKPR prescaling.
- External hardware USART: choose **115200 baud** automatically when the
  best 16x/8x divider differs by at most 2.5% from nominal. Typical examples
  are 10, 12, 16 and 20 MHz; this is not a claim of physical oscillator safety.
- External hardware USART at **8 MHz**: choose **38400**, with approximately
  +0.16% divider error. 115200 at 8 MHz yields approximately -3.55% with
  the best U2X divider, and is therefore not the default.
- Software UART ATtiny84/85: **8 MHz internal RC → 19200**, **8 MHz external
  → 57600**, **16 MHz external → 115200**. Other clocks must pass divider and
  timing validation. 16 MHz/115200 and 8 MHz/57600 pass current cycle-level
  emulator tests with a ±1.5% host-bit-duration perturbation; physical tests
  remain necessary.
- No firmware automatically changes oscillator source, CKDIV8, CLKPR or OSCCAL.

## Corrected timeout regression in the software UART

The previous `uart/soft.inc` executed `WDR` on *each idle polling iteration*.
This indefinitely prevented the watchdog from expiring when there was no host
communication. The new code executes `WDR` **once before** waiting for the
next byte, then idles without resetting the watchdog; hardware will be able
 to time out and start the application if no byte arrives. A test counts the
actual `WDR` opcodes executed by the AVR emulator during the idle loop.

## Remaining risks

Physical board/oscillator/UART timings and actual Arduino IDE 2/AVRDUDE upload
have not been tested. ATtiny Virtual Boot requires the separate patching and
ISP-seed procedure and is not a native hardware BOOTRST solution. Application-callable SPM is now a separate opt-in extension for hardware
Boot Sections >=1024B. Visual startup indication remains future work.
