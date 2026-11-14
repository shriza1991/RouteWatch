"""Read-only inventory service backed by the repository's four synthetic sources."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from shared.v1 import Endpoint
from discovery.inventory import build_inventory

_DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "sandbox" / "fixtures"

class FixtureInventoryService:
    """InventoryService for the local synthetic sandbox; never performs network probes."""
    def __init__(self, fixture_dir: str | Path = _DEFAULT_FIXTURE_DIR):
        self.fixture_dir = Path(fixture_dir).resolve()

    def _load(self, filename: str) -> dict[str, Any]:
        path = (self.fixture_dir / filename).resolve()
        if path.parent != self.fixture_dir or not path.is_file():
            raise ValueError("required discovery fixture is unavailable")
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError("discovery fixture must contain a JSON object")
        return value

    def list_endpoints(self, target_id: str) -> list[Endpoint]:
        if target_id != "local-sandbox":
            raise ValueError("fixture inventory is only available for local-sandbox")
        return build_inventory(
            self._load("journey-recording.v1.json"),
            self._load("reference-inventory.v1.json"),
            self._load("historical-traffic.v1.json"),
            self._load("archived-routes.v1.json"),
        )
