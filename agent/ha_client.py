"""
ha_client.py — Home Assistant REST API client

Đọc HA_URL và HA_TOKEN từ .env hoặc environment variables.
Điều khiển thiết bị qua POST /api/services/<domain>/<service>.
KHÔNG dùng /api/states để điều khiển thiết bị thật.

Dùng:
    from agent.ha_client import HAClient
    ha = HAClient()
    ha.call_service("light", "turn_on", "light.bedroom")
"""

import os
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass   # dotenv không bắt buộc

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [ha_client] %(message)s",
                    datefmt="%H:%M:%S")

TIMEOUT = 5   # giây


class HAClient:
    def __init__(self, dry_run: bool = True):
        self.url     = os.getenv("HA_URL", "http://localhost:8123").rstrip("/")
        self.token   = os.getenv("HA_TOKEN", "")
        self.dry_run = dry_run

        if not self.token and not self.dry_run:
            raise ValueError("HA_TOKEN chưa được set. Thêm vào .env hoặc export HA_TOKEN=...")

        if self.dry_run:
            log.info("dry_run=True — không gọi HA thật")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type":  "application/json",
        }

    def call_service(self, domain: str, service: str,
                     entity_id: str, payload: dict | None = None) -> bool:
        """
        Gọi POST /api/services/<domain>/<service>.
        Trả về True nếu thành công (hoặc dry_run).
        """
        endpoint = f"{self.url}/api/services/{domain}/{service}"
        body     = {"entity_id": entity_id}
        if payload:
            body.update(payload)

        if self.dry_run:
            log.info(f"[DRY RUN] POST {endpoint}  body={body}")
            return True

        if not HAS_REQUESTS:
            log.error("Thư viện 'requests' chưa cài. Chạy: pip install requests")
            return False

        try:
            resp = _requests.post(endpoint, json=body,
                                  headers=self._headers(), timeout=TIMEOUT)
            if resp.status_code in (200, 201):
                log.info(f"OK  {domain}.{service} → {entity_id}")
                return True
            else:
                log.error(f"FAIL {resp.status_code}: {resp.text[:120]}")
                return False
        except Exception as e:
            log.error(f"Request error: {e}")
            return False

    def get_state(self, entity_id: str) -> str | None:
        """Lấy trạng thái hiện tại của entity từ HA (chỉ dùng để đọc)."""
        if self.dry_run:
            log.info(f"[DRY RUN] GET state of {entity_id}")
            return None

        if not HAS_REQUESTS:
            return None

        try:
            resp = _requests.get(
                f"{self.url}/api/states/{entity_id}",
                headers=self._headers(), timeout=TIMEOUT
            )
            if resp.status_code == 200:
                return resp.json().get("state")
        except Exception as e:
            log.error(f"get_state error: {e}")
        return None


if __name__ == "__main__":
    ha = HAClient(dry_run=True)
    ha.call_service("light", "turn_on",  "light.bedroom")
    ha.call_service("light", "turn_off", "light.living_room")
    ha.call_service("switch", "turn_on", "switch.fan_bedroom")