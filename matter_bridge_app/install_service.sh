#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="matter-mqtt-bridge"
SERVICE_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/systemd/${SERVICE_NAME}.service"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}.service"

if [ ! -f "$SERVICE_SRC" ]; then
  echo "Service template not found: $SERVICE_SRC"
  exit 1
fi

chmod +x "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run_bridge_app.sh"
sudo cp "$SERVICE_SRC" "$SERVICE_DST"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

cat <<EOF2
Installed ${SERVICE_NAME}.service.

Start service:
  sudo systemctl start ${SERVICE_NAME}

Check status:
  sudo systemctl status ${SERVICE_NAME}

Follow logs:
  journalctl -u ${SERVICE_NAME} -f

If chip-bridge-app needs elevated network capabilities, prefer assigning
capabilities to the binary instead of running sudo inside systemd, for example:
  sudo setcap 'cap_net_bind_service,cap_net_raw+eip' /home/pi/connectedhomeip/examples/bridge-app/linux/out/debug/chip-bridge-app
EOF2
