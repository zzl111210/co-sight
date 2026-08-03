"""Read-only configuration status and explicit LLM connectivity checks."""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from app.netheal.auth import auth_mode


def _configured_secret(name: str) -> bool:
    value = os.getenv(name, "").strip()
    normalized = value.lower()
    placeholders = {"your-api-key", "your_api_key", "replace-me", "changeme"}
    return bool(
        value
        and "如：" not in value
        and normalized not in placeholders
        and "example" not in normalized
        and "change-me" not in normalized
    )


def model_config_status() -> dict[str, Any]:
    """Return operational configuration without returning secret values."""
    base_url = os.getenv("API_BASE_URL", "").strip()
    model_name = os.getenv("MODEL_NAME", "").strip()
    return {
        "llm": {
            "configured": bool(
                _configured_secret("API_KEY") and base_url and model_name
            ),
            "api_key_present": _configured_secret("API_KEY"),
            "api_base_url": base_url,
            "model_name": model_name,
            "timeout_seconds": int(os.getenv("LLM_TIMEOUT", "60") or 60),
        },
        "optional_tools": {
            "tavily_configured": _configured_secret("TAVILY_API_KEY"),
            "google_search_configured": bool(
                _configured_secret("GOOGLE_API_KEY")
                and os.getenv("SEARCH_ENGINE_ID", "").strip()
            ),
        },
        "security": {
            "auth_mode": auth_mode(),
            "token_secret_configured": _configured_secret(
                "NETHEAL_TOKEN_SECRET"
            ),
            "real_network_write_enabled": False,
        },
    }


def check_llm_connectivity(timeout_seconds: float = 8.0) -> dict[str, Any]:
    """Check the OpenAI-compatible models endpoint without exposing the key."""
    status = model_config_status()
    llm = status["llm"]
    if not llm["configured"]:
        return {
            "ok": False,
            "reason": "LLM configuration is incomplete",
            "model_name": llm["model_name"],
        }

    url = f"{llm['api_base_url'].rstrip('/')}/models"
    started = time.perf_counter()
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {os.environ['API_KEY']}"},
            timeout=max(1.0, min(float(timeout_seconds), 30.0)),
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "ok": response.ok,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "model_name": llm["model_name"],
            "endpoint": llm["api_base_url"],
            "reason": "" if response.ok else "provider rejected the request",
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "model_name": llm["model_name"],
            "endpoint": llm["api_base_url"],
            "reason": str(exc)[:240],
        }
