import os
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .config import load_config
from .routing import decide_route
from .context import build_context
from .providers import call_provider
from .budget import BudgetManager
from .logging_utils import log_request, log_error, log_to_command_center_db
from .observability import (
    LMSTUDIO_BASE_URL,
    OLLAMA_BASE_URL,
    get_last_execution,
)


app = FastAPI(title="Local LLM Router")

CONFIG = load_config()
BUDGET_MANAGER = BudgetManager(CONFIG)
START_TIME = time.time()


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatMetadata(BaseModel):
    intent: Optional[str] = None  # chat | code | reasoning | vision | verify
    priority: Optional[str] = None  # low | normal | high
    route: Optional[str] = None  # openai | anthropic | openrouter
    model: Optional[str] = None  # explicit model id override


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = 0.7
    metadata: Optional[ChatMetadata] = Field(default=None, description="Routing metadata")


async def _probe_lmstudio() -> Dict[str, Any]:
    """Live probe: GET LM Studio /v1/models. Read-only, 3s timeout."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as c:
            resp = await c.get(f"{LMSTUDIO_BASE_URL}/v1/models")
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("id", "?") for m in data.get("data", [])]
            return {"status": "up", "models": models}
        return {"status": "error", "http_status": resp.status_code}
    except Exception as exc:
        return {"status": "down", "error": str(exc)[:120]}


async def _probe_ollama() -> Dict[str, Any]:
    """Live probe: GET Ollama /api/tags. Read-only, 3s timeout."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as c:
            resp = await c.get(f"{OLLAMA_BASE_URL}/api/tags")
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("name", "?") for m in data.get("models", [])]
            return {"status": "up", "models": models}
        return {"status": "error", "http_status": resp.status_code}
    except Exception as exc:
        return {"status": "down", "error": str(exc)[:120]}


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Health endpoint with live infrastructure probes.

    Returns status, uptime, budget snapshots, live LM Studio / Ollama
    status, and last execution metadata. No secrets or request bodies.
    """
    uptime = time.time() - START_TIME

    lmstudio_status, ollama_status = await _probe_lmstudio(), await _probe_ollama()

    return {
        "status": "ok",
        "uptime_seconds": int(uptime),
        "providers": BUDGET_MANAGER.snapshot(),
        "lmstudio_status": lmstudio_status,
        "ollama_status": ollama_status,
        "last_execution": get_last_execution(),
    }


@app.get("/ui/health")
async def ui_health() -> Dict[str, Any]:
    """UI-friendly health endpoint. Forwards the base health payload."""
    return await health()


@app.get("/ui/logs")
async def ui_logs(
    type: str = Query("requests", pattern="^(requests|errors|context)$"),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """Return a tail of router log lines for the dashboard."""

    log_files = {
        "requests": os.path.join("logs", "router-requests.log"),
        "errors": os.path.join("logs", "router-errors.log"),
        "context": os.path.join("logs", "router-context.log"),
    }

    path = log_files.get(type)
    lines: list[str] = []

    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            lines = [ln.rstrip("\n") for ln in all_lines[-limit:]]
        except OSError:
            lines = []

    return {"type": type, "lines": lines}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest) -> Dict[str, Any]:
    try:
        route_decision = decide_route(req, CONFIG, BUDGET_MANAGER)

        trimmed_messages, context_info = build_context(req, CONFIG)

        estimated_prompt_tokens = context_info.get("estimated_prompt_tokens", 0)
        estimated_completion_tokens = req.max_tokens or 512

        if not BUDGET_MANAGER.can_spend(
            provider=route_decision.provider,
            model=route_decision.model,
            prompt_tokens=estimated_prompt_tokens,
            completion_tokens=estimated_completion_tokens,
        ):
            fallback_decision = decide_route(
                req,
                CONFIG,
                BUDGET_MANAGER,
                force_different_provider=True,
            )
            if not BUDGET_MANAGER.can_spend(
                provider=fallback_decision.provider,
                model=fallback_decision.model,
                prompt_tokens=estimated_prompt_tokens,
                completion_tokens=estimated_completion_tokens,
            ):
                raise HTTPException(status_code=429, detail="Budget exceeded for all providers")
            route_decision = fallback_decision

        t0 = time.time()
        response = await call_provider(
            req=req,
            messages=trimmed_messages,
            route_decision=route_decision,
            config=CONFIG,
            budget_manager=BUDGET_MANAGER,
            context_info=context_info,
        )

        log_request(req, route_decision, context_info, CONFIG)

        # ── Command Center telemetry ─────────────────────────────────────
        try:
            _usage = response.get("usage", {}) if isinstance(response, dict) else {}
            _tok_in  = int(_usage.get("prompt_tokens", context_info.get("estimated_prompt_tokens", 0)))
            _tok_out = int(_usage.get("completion_tokens", 0))
            _model   = response.get("model", route_decision.model) if isinstance(response, dict) else route_decision.model
            # Use actual cost from provider when available (OpenRouter returns usage.cost)
            _actual_cost = _usage.get("cost")
            _cost    = float(_actual_cost) if _actual_cost is not None else BUDGET_MANAGER._cost_per_1k(route_decision.provider, _model) * (_tok_in + _tok_out) / 1000.0
            _lat     = int((time.time() - t0) * 1000)
            _agent   = (req.metadata.route or "claw") if req.metadata else "claw"
            log_to_command_center_db(
                provider=route_decision.provider,
                model_name=route_decision.model,
                actual_model=_model,
                agent_name=_agent,
                tokens_in=_tok_in,
                tokens_out=_tok_out,
                cost_usd=_cost,
                latency_ms=_lat,
            )
        except Exception:
            pass  # telemetry must never fail the request
        # ─────────────────────────────────────────────────────────────────

        return response

    except HTTPException:
        raise
    except Exception as exc:
        log_error(exc)
        raise HTTPException(status_code=500, detail="Internal router error") from exc
