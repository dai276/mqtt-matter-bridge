#!/usr/bin/env bash
set -eo pipefail

CHIP_DIR="${CHIP_DIR:-$HOME/connectedhomeip}"
BRIDGE_DIR="$CHIP_DIR/examples/bridge-app/linux"

if [ ! -d "$BRIDGE_DIR" ]; then
  echo "connectedhomeip bridge-app not found at: $BRIDGE_DIR"
  echo "Clone CHIP SDK separately:"
  echo "git clone https://github.com/project-chip/connectedhomeip.git ~/connectedhomeip"
  echo "cd ~/connectedhomeip && git submodule update --init --recursive"
  exit 1
fi

if [ ! -f "$CHIP_DIR/scripts/activate.sh" ]; then
  echo "CHIP SDK activate script not found at: $CHIP_DIR/scripts/activate.sh"
  exit 1
fi

cd "$CHIP_DIR"
source scripts/activate.sh
cd "$BRIDGE_DIR"
gn gen out/debug
ninja -C out/debug
echo "Built: $BRIDGE_DIR/out/debug/chip-bridge-app"