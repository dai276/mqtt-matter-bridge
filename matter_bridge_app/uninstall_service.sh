#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="matter-mqtt-bridge"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"

sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
sudo rm -f "$SERVICE_DST"
sudo systemctl daemon-reload

echo "Uninstalled ${SERVICE_NAME}.service"
