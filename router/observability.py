import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional


LMSTUDIO_BASE_URL = "http://10.10.10.98:1234"
OLLAMA_BASE_URL = "http://10.10.10.175:11434"
OPENROUTER_BASE_URL = "https://openrouter.ai"


_LAST_EXECUTION: Optional[Dict[str, Any]] = None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def execution_host_for_target(target: str) -> str:
    if target == "lmstudio":
        return LMSTUDIO_BASE_URL
    if target == "ollama":
        return OLLAMA_BASE_URL
    if target == "openrouter":
        return OPENROUTER_BASE_URL
    return ""


def execution_mode_for_target(target: str) -> str:
    if target in {"lmstudio", "ollama"}:
        return "local"
    if target == "openrouter":
        return "remote"
    return ""


def record_last_execution(*, target: str, host: str, mode: str) -> None:
    global _LAST_EXECUTION
    ts = time.time()
    _LAST_EXECUTION = {
        "target": target,
        "host": host,
        "mode": mode,
        "timestamp": _iso(ts),
        "timestamp_unix": ts,
    }


def get_last_execution() -> Optional[Dict[str, Any]]:
    return _LAST_EXECUTION


def execution_fields_for_log(target: str) -> Dict[str, str]:
    """Return the three execution fields for request log lines."""
    return {
        "execution_target": target,
        "execution_host": execution_host_for_target(target),
        "execution_mode": execution_mode_for_target(target),
    }
