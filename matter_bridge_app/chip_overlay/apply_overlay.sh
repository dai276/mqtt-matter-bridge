#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHIP_DIR="${CHIP_DIR:-$HOME/connectedhomeip}"
BRIDGE_DIR="$CHIP_DIR/examples/bridge-app/linux"
MAIN_CPP="$BRIDGE_DIR/main.cpp"
BUILD_GN="$BRIDGE_DIR/BUILD.gn"
PATCHER="$SCRIPT_DIR/files/patch_bridge_main.py"
BUILD_PATCHER="$SCRIPT_DIR/files/patch_build_gn.py"

if [ ! -d "$BRIDGE_DIR" ]; then
  echo "connectedhomeip bridge-app not found at: $BRIDGE_DIR"
  echo "Clone CHIP SDK separately:"
  echo "git clone https://github.com/project-chip/connectedhomeip.git ~/connectedhomeip"
  echo "cd ~/connectedhomeip && git submodule update --init --recursive"
  exit 1
fi

if [ ! -f "$MAIN_CPP" ]; then
  echo "bridge-app main.cpp not found at: $MAIN_CPP"
  exit 1
fi

if [ ! -f "$PATCHER" ]; then
  echo "overlay patcher not found at: $PATCHER"
  exit 1
fi

if [ ! -f "$BUILD_GN" ]; then
  echo "bridge-app BUILD.gn not found at: $BUILD_GN"
  exit 1
fi

if [ ! -f "$BUILD_PATCHER" ]; then
  echo "BUILD.gn patcher not found at: $BUILD_PATCHER"
  exit 1
fi

MAIN_BACKUP="$MAIN_CPP.mqtt_matter_bridge_overlay.bak"
BUILD_BACKUP="$BUILD_GN.mqtt_matter_bridge_overlay.bak"
if [ ! -f "$MAIN_BACKUP" ]; then
  cp "$MAIN_CPP" "$MAIN_BACKUP"
  echo "Backed up: $MAIN_BACKUP"
else
  echo "Backup already exists: $MAIN_BACKUP"
fi
if [ ! -f "$BUILD_BACKUP" ]; then
  cp "$BUILD_GN" "$BUILD_BACKUP"
  echo "Backed up: $BUILD_BACKUP"
else
  echo "Backup already exists: $BUILD_BACKUP"
fi

cp "$SCRIPT_DIR/files/mqtt_light_adapter.h" "$BRIDGE_DIR/mqtt_light_adapter.h"
cp "$SCRIPT_DIR/files/mqtt_light_adapter.cpp" "$BRIDGE_DIR/mqtt_light_adapter.cpp"
echo "Copied MQTT adapter overlay files into: $BRIDGE_DIR"

python3 "$PATCHER" "$MAIN_CPP"
python3 "$BUILD_PATCHER" "$BUILD_GN"

echo "Overlay applied to: $MAIN_CPP"
echo
echo "Build with:"
echo "  cd $(cd "$SCRIPT_DIR/.." && pwd)"
echo "  ./build_bridge_app.sh"