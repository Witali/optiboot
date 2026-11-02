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
ifneq ($(filter mini mini_spm mini_middle mini_compact mini_full mini_256 mini_flashread256 mini_check,$(MAKECMDGOALS)),)
ifneq ($(MINI_UNSUPPORTED_REQUESTS),)
$(error Optiboot Mini does not implement requested upstream option(s): $(MINI_UNSUPPORTED_REQUESTS). Use the official optiboot.c target for these capabilities.)
endif
endif

HELPTEXT += "target mini - legacy Basic target; mini_256 / mini_middle / mini_full select editions\n"

.PHONY: mini mini_spm mini_middle mini_compact mini_full mini_256 mini_flashread256 mini_check mini_list mini_test mini_matrix
mini:
	$(MINI_PYTHON) build_mini.py --mcu "$(MINI_SELECTED_MCU)" --f-cpu "$(MINI_SELECTED_FREQ)" --baud "$(MINI_SELECTED_BAUD)" --clock-source "$(MINI_SELECTED_CLOCK)" --boot-bytes "$(MINI_SELECTED_BOOT)" $(MINI_EXTRA_FLAGS)

mini_spm:
	$(MINI_PYTHON) build_mini.py --mcu "$(MINI_SELECTED_MCU)" --f-cpu "$(MINI_SELECTED_FREQ)" --baud "$(MINI_SELECTED_BAUD)" --clock-source "$(MINI_SELECTED_CLOCK)" --boot-bytes 1024 --universal-signature --app-spm --output-dir "output/spm/$(MINI_SELECTED_MCU)" $(MINI_EXTRA_FLAGS)

mini_middle mini_compact:
	$(MINI_PYTHON) generate_firmware.py "$(MINI_SELECTED_MCU)" middle "$(MINI_SELECTED_FREQ)" --baud "$(MINI_SELECTED_BAUD)" --clock "$(MINI_SELECTED_CLOCK)"

mini_full:
	$(MINI_PYTHON) generate_firmware.py "$(MINI_SELECTED_MCU)" full "$(MINI_SELECTED_FREQ)" --baud "$(MINI_SELECTED_BAUD)" --clock "$(MINI_SELECTED_CLOCK)"

mini_256 mini_flashread256:
	$(MINI_PYTHON) generate_firmware.py "$(MINI_SELECTED_MCU)" mini "$(MINI_SELECTED_FREQ)" --baud "$(MINI_SELECTED_BAUD)" --clock "$(MINI_SELECTED_CLOCK)"

mini_check: mini mini_test

mini_list:
	$(MINI_PYTHON) generate_firmware.py --list

mini_test:
	$(MINI_PYTHON) -m unittest discover -s mini_tests -v
	$(MINI_PYTHON) -m unittest discover -s generator_tests -v

mini_matrix:
	$(MINI_PYTHON) verify_editions.py --all-clocks --smoke --stress
