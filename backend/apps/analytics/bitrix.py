from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings


class BitrixError(RuntimeError):
    pass


@dataclass
class BitrixClient:
    webhook_url: str
    timeout: int = 30

    @classmethod
    def from_settings(cls) -> "BitrixClient":
        webhook_url = settings.BITRIX24["WEBHOOK_URL"]
        if not webhook_url:
            raise BitrixError("BITRIX24_WEBHOOK_URL is not configured")
        return cls(webhook_url=webhook_url, timeout=settings.BITRIX24["TIMEOUT_SECONDS"])

    def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        return self.call_raw(method, payload).get("result")

    def call_raw(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.post(
            f"{self.webhook_url}{method}.json",
            json=payload or {},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise BitrixError(f"{data.get('error')}: {data.get('error_description')}")
        return data

    def batch(self, commands: dict[str, str], halt: bool = False) -> dict[str, Any]:
        data = self.call_raw("batch", {"halt": int(halt), "cmd": commands})
        result = data.get("result", {})
        errors = result.get("result_error") or []
        if errors and halt:
            raise BitrixError(f"Batch failed: {errors}")
        return result

    def list_all(self, method: str, payload: dict[str, Any] | None = None, result_key: str | None = None):
        base_payload = payload.copy() if payload else {}
        start = 0
        while True:
            page_payload = {**base_payload, "start": start}
            response = requests.post(
                f"{self.webhook_url}{method}.json",
                json=page_payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise BitrixError(f"{data.get('error')}: {data.get('error_description')}")

            result = data.get("result", [])
            if result_key and isinstance(result, dict):
                items = result.get(result_key, [])
            else:
                items = result
            yield from items

            next_start = data.get("next")
            if next_start is None:
                break
            start = next_start
