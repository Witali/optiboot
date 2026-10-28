#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 build.py optiboot_mini328_final optiboot_mini328_final_tiny
python3 test_emulator.py
python3 differential_test.py
python3 test_invariants.py
