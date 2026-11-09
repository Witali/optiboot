#!/usr/bin/env python3
"""Rebuild the active firmware matrix and run the imported compatibility suites."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-build', action='store_true', help='Reuse matrices already built by this runner')
    args = parser.parse_args()
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}

    def run(*command):
        subprocess.run([sys.executable, *command], cwd=ROOT, env=env, check=True)

    if not args.no_build:
        run('build_dual.py', '--all', '--jobs', '6')
        # Independent constant-signature builds exercise all MCU reset/SPM models,
        # including fallback silicon-signature paths, without old external snapshots.
        run('build_dual.py', '--all', '--jobs', '6', '--signature-source', 'constants',
            '--output-dir', str(ROOT/'output/validation_constants'))
    run('-m', 'unittest', 'discover', '-s', 'mini_tests', '-v')
    run('-m', 'unittest', 'discover', '-s', 'generator_tests', '-v')


if __name__ == '__main__':
    main()
