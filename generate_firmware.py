#!/usr/bin/env python3
"""Launch the canonical Mini/Middle/Full generator from the repository root."""
from pathlib import Path
import runpy
import sys


if __name__ == '__main__':
    implementation = Path(__file__).resolve().parent/'optiboot/bootloaders/optiboot/generate_firmware.py'
    sys.path.insert(0, str(implementation.parent))
    runpy.run_path(str(implementation), run_name='__main__')
