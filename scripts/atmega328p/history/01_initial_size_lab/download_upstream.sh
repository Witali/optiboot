#!/bin/sh
# Download the complete original sources of Optiboot from official GitHub.
set -eu
BASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BASE_DIR="$BASE_DIR/../../../../optiboot/bootloaders/optiboot_328p/history/01_initial_size_lab"
mkdir -p "$BASE_DIR/upstream"
if command -v git >/dev/null 2>&1; then
  if [ ! -d "$BASE_DIR/upstream/original_repo/.git" ]; then
    git clone --depth=1 https://github.com/Optiboot/optiboot.git "$BASE_DIR/upstream/original_repo"
  else
    git -C "$BASE_DIR/upstream/original_repo" pull --ff-only
  fi
else
  echo 'git is required to fetch the full upstream source tree' >&2
  exit 1
fi
printf '\nUpstream Optiboot source: %s\n' "$BASE_DIR/upstream/original_repo/optiboot/bootloaders/optiboot/optiboot.c"
