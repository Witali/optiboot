# Additional Optiboot Mini targets. Safe to include from upstream Makefile.custom.
# The main Optiboot Makefile, original optiboot.c, and other targets remain unchanged.

# Follow explicit settings in the calling project or on the command line.
# Upstream's file-local MCU_TARGET defaults to atmega168 even for an unspecific make;
# do not inherit that default accidentally. Prefer MINI_MCU, then MCU, then an
# explicitly exported/command-line MCU_TARGET, and finally Arduino Uno/328P.
ifneq ($(strip $(MINI_MCU)),)
MINI_SELECTED_MCU := $(MINI_MCU)
else ifneq ($(strip $(MCU)),)
MINI_SELECTED_MCU := $(MCU)
else ifneq ($(filter command\ line environment environment\ override,$(origin MCU_TARGET)),)
MINI_SELECTED_MCU := $(MCU_TARGET)
else
MINI_SELECTED_MCU := atmega328p
endif

# Project minimum F_CPU = 8 MHz (validated in build_mini.py).
# Explicit F_CPU wins. Tiny84/85 default to 8 MHz actual CPU clock even when
# upstream Makefile defines an AVR_FREQ for unrelated Arduino boards.
MINI_SOFT_CHIP := $(filter attiny84 attiny85,$(MINI_SELECTED_MCU))
MINI_SELECTED_FREQ := $(if $(F_CPU),$(F_CPU),$(if $(MINI_SOFT_CHIP),8000000,$(if $(AVR_FREQ),$(patsubst %L,%,$(AVR_FREQ)),16000000)))
MINI_SELECTED_BAUD := $(if $(MINI_BAUD_RATE),$(MINI_BAUD_RATE),$(if $(MINI_SOFT_CHIP),auto,$(if $(BAUD_RATE),$(BAUD_RATE),auto)))
MINI_SELECTED_CLOCK := $(if $(MINI_CLOCK_SOURCE),$(MINI_CLOCK_SOURCE),$(if $(CLOCK_SOURCE),$(CLOCK_SOURCE),$(if $(MINI_SOFT_CHIP),internal_rc,external_crystal)))
MINI_SELECTED_BOOT := $(if $(MINI_BOOT_BYTES),$(MINI_BOOT_BYTES),auto)
MINI_EXTRA_FLAGS := $(if $(filter 1 yes true,$(MINI_ALLOW_OVERCLOCK)),--allow-overclock,)
MINI_EXTRA_FLAGS += $(if $(filter 1 yes true,$(MINI_ALLOW_BAUD_ERROR)),--allow-baud-error,)
MINI_EXTRA_FLAGS += $(if $(filter 1 yes true,$(MINI_OLD_AVRDUDE_EEPROM)),--legacy-eeprom-byte-address,)
MINI_EXTRA_FLAGS += $(if $(filter 1 yes true,$(MINI_UNIVERSAL_SIGNATURE)),--universal-signature,)
MINI_EXTRA_FLAGS += $(if $(filter 1 yes true,$(MINI_COMPACT_SIGNATURE)),--compact-signature,)
MINI_EXTRA_FLAGS += $(if $(filter 1 yes true,$(MINI_APP_SPM)),--app-spm,)
MINI_EXTRA_FLAGS += $(if $(filter 1 yes true,$(MINI_MCUSR_PARITY)),--mcusr-parity,)
MINI_PYTHON ?= python3

# Fail rather than silently ignoring official Optiboot options that this
# size-optimized assembly does not implement.  Keep the official Optiboot
# Makefile/optiboot.c targets available for those builds.
MINI_UNSUPPORTED_UPSTREAM_OPTIONS := LED LED_START_FLASHES LED_DATA_FLASH LED_START_ON RS485 UART WDTTIME \
    SINGLESPEED SOFT_UART NO_START_APP_ON_POR START_APP_ON_EXTR OSCCAL_VALUE \
    APP_NOSPM NO_APP_SPM BIGBOOT VIRTUAL_BOOT_PARTITION CUSTOM_VERSION OPTIBOOT_CUSTOMVER
MINI_UNSUPPORTED_REQUESTS = $(strip $(foreach opt,$(MINI_UNSUPPORTED_UPSTREAM_OPTIONS),$(if $(filter undefined,$(origin $(opt))),,$(opt))))
ifneq ($(filter mini mini_spm mini_compat mini_small512 mini328_spm512 mini_clone511 mini_644compact mini_check mini328_sig512,$(MAKECMDGOALS)),)
ifneq ($(MINI_UNSUPPORTED_REQUESTS),)
$(error Optiboot Mini does not implement requested upstream option(s): $(MINI_UNSUPPORTED_REQUESTS). Use the official optiboot.c target for these capabilities.)
endif
endif

HELPTEXT += "target mini - Auto-select classic AVR from MINI_MCU/MCU/explicit MCU_TARGET (default ATmega328P)\n"

.PHONY: mini mini_spm mini_check mini_list mini_test
mini:
	$(MINI_PYTHON) build_mini.py --mcu "$(MINI_SELECTED_MCU)" --f-cpu "$(MINI_SELECTED_FREQ)" --baud "$(MINI_SELECTED_BAUD)" --clock-source "$(MINI_SELECTED_CLOCK)" --boot-bytes "$(MINI_SELECTED_BOOT)" $(MINI_EXTRA_FLAGS)

# Full Optiboot 8.x-compatible app SPM entry at BOOT_START+2.
# The extended 1024-byte section is intentional; BOOTSZ fuses must match.
mini_spm:
	$(MINI_PYTHON) build_mini.py --mcu "$(MINI_SELECTED_MCU)" --f-cpu "$(MINI_SELECTED_FREQ)" --baud "$(MINI_SELECTED_BAUD)" --clock-source "$(MINI_SELECTED_CLOCK)" --boot-bytes "1024" --output-dir "output/spm/$(MINI_SELECTED_MCU)" $(MINI_EXTRA_FLAGS) --universal-signature --app-spm

# Explicit 512-byte app-SPM ABI for 21 approved 8/16/32KiB ATmega parts.
# Refuses the unsupported 64/128/256KiB and Virtual Boot parts. BOOTSZ fuses
# MUST be configured for exactly 512 bytes before flashing the resulting HEX.
.PHONY: mini_small512
mini_small512:
	$(MINI_PYTHON) build_mini.py --mcu "$(MINI_SELECTED_MCU)" --f-cpu "$(MINI_SELECTED_FREQ)" --baud "$(MINI_SELECTED_BAUD)" --clock-source "$(MINI_SELECTED_CLOCK)" --boot-bytes 512 --app-spm-512 --output-dir "output/small512/$(MINI_SELECTED_MCU)" $(MINI_EXTRA_FLAGS)

# The preferred 38-target source build.  Each MCU compiles optiboot_mini.S
# with its own device profile and just the necessary 3-byte signature.
# 21 compatible ATmega get compact 512B SPM; larger ATmega use full 1024B.
# Four virtual-boot ATtiny devices use DIRECT application SPM instead:
# no BOOT_START+2 ABI; SELFPRGEN and reset-vector patching are still required.
.PHONY: mini_compat
mini_compat:
	$(MINI_PYTHON) build_mini_compat.py --mcu "$(MINI_SELECTED_MCU)" --f-cpu "$(MINI_SELECTED_FREQ)" --baud "$(MINI_SELECTED_BAUD)" --clock-source "$(MINI_SELECTED_CLOCK)" $(MINI_EXTRA_FLAGS)

mini_check: mini
	$(MINI_PYTHON) run_tests.py

mini_list:
	$(MINI_PYTHON) build_mini.py --list-chips

mini_test:
	$(MINI_PYTHON) run_tests.py

# Optional ATmega328P serial compatibility image; not the normal default.
# 512-byte BOOTSZ, 16 MHz, 115200; dual signature read methods but UNIVERSAL
# fuse/lock reads return zero. Never use this for true fuse programming.
.PHONY: mini328_sig512
mini328_sig512:
	$(MINI_PYTHON) build_mini.py --mcu atmega328p --f-cpu 16000000 --baud 115200 --boot-bytes 512 --universal-signature --compact-signature --output-dir output/atmega328p-sig512

# SPM ABI-preserving 512B Optiboot Mini variant for ATmega328P.
# GET_SIGN_ON string and SET_PARAMETER payload handling are intentionally
# disabled to keep the SPM ABI, Flash, EEPROM and dual signature reads.
.PHONY: mini328_spm512
mini328_spm512:
	$(MINI_PYTHON) build_mini.py --mcu atmega328p --f-cpu 16000000 --baud 115200 --clock-source external_crystal --boot-bytes 512 --app-spm-512 --output-dir output/spm512/atmega328p

# Historical target spelling retained for automation. No binary cloning:
# every image is assembled from optiboot_mini.S with MCU-only defines.
# Prefer: make mini_compat MINI_MCU=<device>
.PHONY: mini_clone511
mini_clone511:
	$(MINI_PYTHON) build_mini_clone511.py --mcu "$(MINI_SELECTED_MCU)" --f-cpu "$(MINI_SELECTED_FREQ)" --baud "$(if $(filter auto,$(MINI_SELECTED_BAUD)),115200,$(MINI_SELECTED_BAUD))" --clock-source "$(MINI_SELECTED_CLOCK)" --output-dir "output/source511"

# 64KiB ATmega644 family. Code+sig+version 509 bytes, *physical* BOOTSZ 1024.
# This is NOT a 512-byte fuse option; base=0xFC00 and application=0x0000..0xFBFF.
.PHONY: mini_644compact
mini_644compact:
	$(MINI_PYTHON) build_mini.py --mcu "$(MINI_SELECTED_MCU)" --f-cpu "$(MINI_SELECTED_FREQ)" --baud "$(MINI_SELECTED_BAUD)" --clock-source "$(MINI_SELECTED_CLOCK)" --boot-bytes 1024 --compact-644 --output-dir "output/compact644/$(MINI_SELECTED_MCU)" $(MINI_EXTRA_FLAGS)
