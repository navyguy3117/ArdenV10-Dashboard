import os
import time
from typing import Any, Dict, List

import httpx

from .logging_utils import logger, log_error


OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

LMSTUDIO_API_URL = "http://10.10.10.98:1234/v1/chat/completions"
LMSTUDIO_MODELS_URL = "http://10.10.10.98:1234/api/v0/models"


async def _get_lmstudio_loaded_model() -> str:
    """Return the first currently-loaded model ID from LM Studio, or empty string."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as c:
            resp = await c.get(LMSTUDIO_MODELS_URL)
        if resp.status_code == 200:
            data = resp.json()
            for m in data.get("data", []):
                if m.get("state") == "loaded":
                    return m.get("id", "")
    except Exception:
        pass
    return ""


async def _call_lmstudio(
    req: Any,
    messages: List[Any],
    route_decision: Any,
    budget_manager: Any,
    context_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Call LM Studio's OpenAI-compatible endpoint at 10.10.10.98:1234."""

    # Use the requested model or discover the loaded one
    model = route_decision.model
    if not model or model in ("auto", "local", "lmstudio"):
        model = await _get_lmstudio_loaded_model()
    if not model:
        raise RuntimeError("LM Studio: no model loaded")

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }
    if req.max_tokens is not None:
        payload["max_tokens"] = req.max_tokens
    if req.temperature is not None:
        payload["temperature"] = req.temperature

    try:
        timeout = httpx.Timeout(120.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(LMSTUDIO_API_URL, json=payload,
                                     headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        data = resp.json()

        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        prompt_tokens     = int(usage.get("prompt_tokens", context_info.get("estimated_prompt_tokens", 0)))
        completion_tokens = int(usage.get("completion_tokens", 0))

        # Local inference is free — record 0 cost
        budget_manager.record_spend(
            provider="local",
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return data

    except Exception as exc:
        log_error(exc, extra={"provider": "lmstudio", "model": model})
        raise



async def _call_openrouter(
    req: Any,
    messages: List[Any],
    route_decision: Any,
    budget_manager: Any,
    context_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Call OpenRouter's chat completions API.

    Uses OPENROUTER_API_KEY from the environment. Models are passed through
    from the routing decision (e.g. "openrouter/auto" or a specific model id).
    """

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in the environment")

    model = route_decision.model

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # Optional but recommended by OpenRouter for analytics/debugging:
        "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "https://openclaw.local"),
        "X-Title": os.getenv("OPENROUTER_X_TITLE", "OpenClaw Local Router"),
    }

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": m.role, "content": m.content} for m in messages
        ],
    }

    # Pass through common OpenAI-style parameters when present
    if req.max_tokens is not None:
        payload["max_tokens"] = req.max_tokens
    if req.temperature is not None:
        payload["temperature"] = req.temperature

    # Basic retry loop
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            timeout = httpx.Timeout(60.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(OPENROUTER_API_URL, headers=headers, json=payload)

            if resp.status_code >= 400:
                # Log body for debugging but don't expose upstream details directly.
                log_error(
                    RuntimeError(f"OpenRouter HTTP {resp.status_code}"),
                    extra={"body": resp.text[:2000]},
                )
                # Non-retryable for 4xx except 429; 5xx we retry.
                if resp.status_code < 500 and resp.status_code != 429:
                    resp.raise_for_status()

            data = resp.json()

            # Record budget usage using returned usage if available, else estimates
            usage = data.get("usage", {}) if isinstance(data, dict) else {}
            prompt_tokens = int(
                usage.get("prompt_tokens", context_info.get("estimated_prompt_tokens", 0))
            )
            completion_tokens = int(usage.get("completion_tokens", 0))

            budget_manager.record_spend(
                provider=route_decision.provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

            return data

        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log_error(exc, extra={"attempt": attempt + 1, "provider": "openrouter"})
            # Backoff before retrying
            time.sleep(min(2 ** attempt, 5))

    # If we exhaust retries, raise the last exception
    if last_exc is not None:
        raise last_exc

    raise RuntimeError("Unknown OpenRouter error")


async def call_provider(
    req: Any,
    messages: List[Any],
    route_decision: Any,
    config: Dict[str, Any],
    budget_manager: Any,
    context_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Dispatch to the appropriate upstream provider.

    For now, only OpenRouter is implemented. OpenAI and Anthropic still
    return a local stubbed response so that wiring can be exercised without
    hitting those APIs.
    """

    provider = route_decision.provider
    model = route_decision.model

    if provider == "openrouter":
        logger.info("Calling OpenRouter model=%s", model)
        return await _call_openrouter(req, messages, route_decision, budget_manager, context_info)

    if provider in ("lmstudio", "local"):
        logger.info("Calling LM Studio model=%s", model)
        return await _call_lmstudio(req, messages, route_decision, budget_manager, context_info)

    # Temporary stubs for other providers until they are wired up.
    logger.info("Calling provider=%s model=%s (stubbed)", provider, model)

    now = int(time.time())
    content = "This is a stubbed response from the local LLM router (no upstream call yet)."

    usage_tokens = context_info.get("estimated_prompt_tokens", 0)
    budget_manager.record_spend(
        provider=provider,
        model=model,
        prompt_tokens=usage_tokens,
        completion_tokens=0,
    )

    return {
        "id": f"chatcmpl-local-{now}",
        "object": "chat.completion",
        "created": now,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": usage_tokens,
            "completion_tokens": 0,
            "total_tokens": usage_tokens,
        },
    }
