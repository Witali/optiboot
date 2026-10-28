# Build and check the experimental ATmega328P assembly implementation.
PYTHON ?= python3
SCRIPTS := ../../../scripts/atmega328p

.PHONY: all check test

all:
	$(PYTHON) $(SCRIPTS)/build.py

# Check the supplied research image without an AVR toolchain.
check:
	$(PYTHON) $(SCRIPTS)/run_tests.py

# Rebuild and check the newly generated image.
test:
	$(PYTHON) $(SCRIPTS)/run_tests.py --build
