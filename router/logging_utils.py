import logging
import os
from typing import Any, Dict

import yaml


logger = logging.getLogger("router")
logger.setLevel(logging.INFO)

handler = logging.StreamHandler()
formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def log_request(req: Any, route_decision: Any, context_info: Dict[str, Any], config: Dict[str, Any]) -> None:
    cfg = config.get("logging", {})
    path = cfg.get("request_log", "logs/router-requests.log")
    _ensure_dir(path)

    forced_route = getattr(route_decision, "forced_route", False)

    record = {
        "provider": route_decision.provider,
        "model": route_decision.model,
        "tier": route_decision.tier,
        "intent": route_decision.intent,
        "priority": route_decision.priority,
        "forced_route": forced_route,
        "forced_provider": route_decision.forced_provider,
        "forced_model": route_decision.forced_model,
        "estimated_tokens_in": context_info.get("estimated_prompt_tokens", 0),
        "reason": route_decision.reason,
    }

    with open(path, "a", encoding="utf-8") as f:
        f.write(str(record) + "\n")


def log_error(exc: Exception, extra: Dict[str, Any] | None = None) -> None:
    logger.exception("Router error: %s", exc)
    path = os.path.join("logs", "router-errors.log")
    _ensure_dir(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"ERROR: {exc}\n")
        if extra:
            f.write(str(extra) + "\n")


def log_context(context_info: Dict[str, Any], config: Dict[str, Any]) -> None:
    cfg = config.get("logging", {})
    path = cfg.get("context_log", "logs/router-context.log")
    _ensure_dir(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(str(context_info) + "\n")


# ── Command Center DB telemetry ──────────────────────────────────────────────

import sqlite3 as _sqlite3
import urllib.request as _urllib_req
import json as _json
from pathlib import Path as _Path
from datetime import datetime as _datetime, date as _date, timezone as _timezone


_CC_DB  = str(_Path.home() / ".openclaw/workspace/command_center.db")
_CC_URL = "http://127.0.0.1:3000/api/routing"   # triggers SSE broadcast


def log_to_command_center_db(
    *,
    provider: str,
    model_name: str,
    actual_model: str,
    agent_name: str = "claw",
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    latency_ms: int = 0,
) -> None:
    """Write a completed routing call into command_center.db for the dashboard.

    Never raises — a telemetry failure must not affect the main call path.
    Provider names are normalised to match the dashboard's expectations:
      lmstudio / ollama → local

    Strategy: try the HTTP API first (fires SSE + budget update); fall back to
    direct SQLite write if the command center is unreachable.
    """
    _PROV_MAP = {"lmstudio": "local", "ollama": "local"}
    provider = _PROV_MAP.get(provider, provider)

    payload = _json.dumps({
        "provider":     provider,
        "model_name":   model_name,
        "actual_model": actual_model,
        "agent_name":   agent_name,
        "tokens_in":    tokens_in,
        "tokens_out":   tokens_out,
        "cost_usd":     cost_usd,
        "latency_ms":   latency_ms,
    }).encode()

    # ── 1. Try HTTP POST so the dashboard gets a live SSE broadcast ──────────
    try:
        req = _urllib_req.Request(
            _CC_URL, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _urllib_req.urlopen(req, timeout=2):
            pass
        return  # success — command center handled DB + budget + SSE
    except Exception:
        pass  # command center unreachable; fall through to direct write

    # ── 2. Fallback: write directly to SQLite (no SSE, but at least persisted) ─
    try:
        ts           = _datetime.now(tz=_timezone.utc).isoformat()
        period_start = _date.today().replace(day=1).isoformat()
        conn = _sqlite3.connect(_CC_DB, timeout=3)
        conn.execute(
            """INSERT INTO routing_calls
               (timestamp, provider, model_name, actual_model, agent_name,
                tokens_in, tokens_out, cost_usd, latency_ms)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (ts, provider, model_name, actual_model, agent_name,
             tokens_in, tokens_out, cost_usd, latency_ms),
        )
        # Keep budget table in sync too
        conn.execute(
            """INSERT INTO budget (period_start, provider, total_spent) VALUES (?,?,?)
               ON CONFLICT(period_start, provider) DO UPDATE SET
                   total_spent = total_spent + excluded.total_spent""",
            (period_start, provider, cost_usd),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # telemetry must never crash the router
