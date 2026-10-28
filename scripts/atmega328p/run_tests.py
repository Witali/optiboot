#!/usr/bin/env python3
"""Run the five imported AVR model suites against supplied or rebuilt firmware."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCE = REPO / "optiboot/bootloaders/optiboot_328p"
NAME = "optiboot_328_verified"
SUITES = (
    "test_eeprom.py",
    "test_universal.py",
    "test_differential_upstream.py",
    "test_strict_datasheet.py",
    "test_protocol_limits.py",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--build", action="store_true", help="rebuild with LLVM AVR tools before testing")
    mode.add_argument("--firmware", type=Path, help="test a specific 512-byte BIN")
    args = parser.parse_args()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    if args.build:
        required = ("clang", "llvm-objcopy", "llvm-objdump", "readelf")
        missing = [name for name in required if shutil.which(name) is None]
        if missing:
            parser.error("missing build tools on PATH: " + ", ".join(missing))
        subprocess.run([sys.executable, str(HERE / "build.py")], check=True, env=env)
        firmware = SOURCE / "build" / (NAME + ".bin")
    else:
        firmware = args.firmware or SOURCE / (NAME + ".bin")
    firmware = firmware.resolve()
    image = firmware.read_bytes()
    if len(image) != 512:
        parser.error(f"expected a 512-byte BIN; received {len(image)} bytes")
    env["OPTIBOOT_328P_BINARY"] = str(firmware)
    print(f"Firmware: {firmware.name}; SHA256 {hashlib.sha256(image).hexdigest()}", flush=True)
    for suite in SUITES:
        print(f"\nRunning {suite}", flush=True)
        subprocess.run([sys.executable, str(HERE / suite)], check=True, env=env)
    print("\nAll five software-model suites passed. Physical-hardware testing is pending.")


if __name__ == "__main__":
    main()
