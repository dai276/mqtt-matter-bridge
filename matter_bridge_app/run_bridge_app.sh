#!/usr/bin/env bash
set -euo pipefail

CHIP_DIR="${CHIP_DIR:-$HOME/connectedhomeip}"
BRIDGE_APP="$CHIP_DIR/examples/bridge-app/linux/out/debug/chip-bridge-app"
BLE_CONTROLLER="${BLE_CONTROLLER:-}"
RUN_WITH_SUDO="${RUN_WITH_SUDO:-1}"

if [ ! -x "$BRIDGE_APP" ]; then
  echo "chip-bridge-app not built. Run ./build_bridge_app.sh first."
  exit 1
fi

cmd=("$BRIDGE_APP")
if [ -n "$BLE_CONTROLLER" ]; then
  cmd+=(--ble-controller "$BLE_CONTROLLER")
fi

if [ "$RUN_WITH_SUDO" = "1" ]; then
  exec sudo "${cmd[@]}"
else
  exec "${cmd[@]}"
fi
