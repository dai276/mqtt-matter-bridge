#!/usr/bin/env bash
set -euo pipefail

CHIP_DIR="${CHIP_DIR:-$HOME/connectedhomeip}"
BRIDGE_DIR="$CHIP_DIR/examples/bridge-app/linux"
MAIN_CPP="$BRIDGE_DIR/main.cpp"
BUILD_GN="$BRIDGE_DIR/BUILD.gn"
MAIN_BACKUP="$MAIN_CPP.mqtt_matter_bridge_overlay.bak"
BUILD_BACKUP="$BUILD_GN.mqtt_matter_bridge_overlay.bak"

if [ ! -f "$MAIN_BACKUP" ]; then
  echo "No overlay backup found at: $MAIN_BACKUP"
  exit 1
fi

cp "$MAIN_BACKUP" "$MAIN_CPP"
echo "Restored original bridge-app main.cpp from: $MAIN_BACKUP"

if [ -f "$BUILD_BACKUP" ]; then
  cp "$BUILD_BACKUP" "$BUILD_GN"
  echo "Restored original bridge-app BUILD.gn from: $BUILD_BACKUP"
fi

rm -f "$BRIDGE_DIR/mqtt_light_adapter.h" "$BRIDGE_DIR/mqtt_light_adapter.cpp"
echo "Removed MQTT adapter overlay files from: $BRIDGE_DIR"
