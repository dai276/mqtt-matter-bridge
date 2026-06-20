"""Home Assistant REST API client. Uses /api/services only for control."""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

if importlib.util.find_spec("dotenv") is not None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")

if importlib.util.find_spec("requests") is not None:
    import requests as _requests
    HAS_REQUESTS = True
else:
    _requests = None
    HAS_REQUESTS = False

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [ha_client] %(message)s", datefmt="%H:%M:%S")
TIMEOUT = 5
SUPPORTED_DOMAINS = {"light", "switch", "climate", "media_player"}
SUPPORTED_SERVICES = {"turn_on", "turn_off"}


class HAClient:
    def __init__(self, dry_run: bool = True):
        self.url = os.getenv("HA_URL", "http://localhost:8123").rstrip("/")
        self.token = os.getenv("HA_TOKEN", "")
        self.dry_run = dry_run
        if not self.token and not self.dry_run:
            raise ValueError("HA_TOKEN chưa được set. Thêm vào .env hoặc export HA_TOKEN=...")
        if self.dry_run:
            log.info("dry_run=True — không gọi HA thật")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def call_service(self, domain: str, service: str, entity_id: str, payload: dict | None = None) -> bool:
        if domain not in SUPPORTED_DOMAINS or service not in SUPPORTED_SERVICES:
            log.error("Unsupported HA service call: %s.%s for %s", domain, service, entity_id)
            return False
        endpoint = f"{self.url}/api/services/{domain}/{service}"
        body = {"entity_id": entity_id}
        if payload:
            body.update(payload)
        if self.dry_run:
            log.info("[DRY RUN] POST %s body=%s", endpoint, body)
            return True
        if not HAS_REQUESTS:
            log.error("Thư viện 'requests' chưa cài. Chạy: pip install requests")
            return False
        try:
            resp = _requests.post(endpoint, json=body, headers=self._headers(), timeout=TIMEOUT)
            if resp.status_code in (200, 201):
                log.info("[HA] OK %s: %s", resp.status_code, resp.text[:200])
                return True
            log.error("[HA] FAIL %s: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as exc:
            log.error("Request error: %s", exc)
            return False

    def get_state(self, entity_id: str) -> str | None:
        """Read-only helper; never used to control devices."""
        if self.dry_run or not HAS_REQUESTS:
            return None
        try:
            resp = _requests.get(f"{self.url}/api/states/{entity_id}", headers=self._headers(), timeout=TIMEOUT)
            if resp.status_code == 200:
                return resp.json().get("state")
        except Exception as exc:
            log.error("get_state error: %s", exc)
        return None


if __name__ == "__main__":
    ha = HAClient(dry_run=True)
    for domain, entity in [("light", "light.bedroom_light"), ("switch", "switch.living_room_ceiling_fan"), ("climate", "climate.bedroom_ac"), ("media_player", "media_player.living_room_tv")]:
        ha.call_service(domain, "turn_on", entity)
        ha.call_service(domain, "turn_off", entity)