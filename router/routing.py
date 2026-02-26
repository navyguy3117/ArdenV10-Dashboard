from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .budget import BudgetManager
from .logging_utils import logger


@dataclass
class RouteDecision:
    provider: str
    model: str
    tier: str
    intent: str
    priority: str
    forced_route: bool
    forced_provider: Optional[str] = None
    forced_model: Optional[str] = None
    reason: str = ""


INTENTS = {"chat", "code", "reasoning", "vision", "verify"}
PRIORITIES = {"low", "normal", "high"}


def _detect_intent(messages: List[Any], config: Dict[str, Any]) -> str:
    # If nothing else, default to chat
    last_user = next((m for m in reversed(messages) if m.role == "user"), None)
    if not last_user:
        return "chat"

    content = str(last_user.content).lower()
    intent_keywords = config.get("routing", {}).get("intent_keywords", {})

    for intent, keywords in intent_keywords.items():
        for kw in keywords:
            if kw in content:
                if intent in INTENTS:
                    return intent

    # Vision: simple heuristic – if content mentions image-like words
    if any(k in content for k in ["image", "screenshot", "vision"]):
        return "vision"

    return "chat"


def _normalize_priority(metadata_priority: Optional[str], config: Dict[str, Any]) -> str:
    if metadata_priority and metadata_priority in PRIORITIES:
        return metadata_priority
    return config.get("routing", {}).get("default_priority", "normal")


def _pick_from_fallback_chain(intent: str, config: Dict[str, Any]) -> List[Tuple[str, str]]:
    chain = config.get("routing", {}).get("fallback_chain", {}).get(intent, [])
    return [(p, t) for p, t in chain]


def _resolve_model(config: Dict[str, Any], provider: str, tier: str) -> Optional[str]:
    provider_cfg = config.get("providers", {}).get(provider, {})
    tiers = provider_cfg.get("tiers", {})
    tier_cfg = tiers.get(tier, {})
    return tier_cfg.get("default_model")


def decide_route(
    req: Any,
    config: Dict[str, Any],
    budget_manager: BudgetManager,
    force_different_provider: bool = False,
) -> RouteDecision:
    metadata = req.metadata or None

    # 1) Determine intent
    intent = metadata.intent if metadata and metadata.intent in INTENTS else _detect_intent(req.messages, config)

    # 2) Determine priority
    priority = _normalize_priority(metadata.priority if metadata else None, config)

    # 3) Handle routing overrides
    overrides_cfg = config.get("routing", {}).get("overrides", {})
    allow_route_override = overrides_cfg.get("allow_route_override", True)
    allow_model_override = overrides_cfg.get("allow_model_override", True)

    forced_provider = None
    forced_model = None
    forced_route = False

    if metadata:
        if metadata.route and allow_route_override:
            forced_provider = metadata.route
            forced_route = True
        if metadata.model and allow_model_override:
            forced_model = metadata.model
            forced_route = True

    # 4) Build fallback chain
    chain = _pick_from_fallback_chain(intent, config)
    if forced_provider:
        # override provider in chain, keep tiers
        chain = [(forced_provider, tier) for _, tier in chain]

    if force_different_provider and chain:
        # Skip the first provider in chain to enforce "different" provider
        primary_provider = chain[0][0]
        chain = [(p, t) for p, t in chain if p != primary_provider]

    if not chain:
        raise ValueError("No routing chain configured for intent: %s" % intent)

    # 5) Iterate chain until we find a viable provider/model
    for provider, tier in chain:
        model = forced_model or _resolve_model(config, provider, tier)
        if not model:
            continue

        # Budget-level precheck: use a tiny estimated cost just to see if provider is hard-disabled
        if not budget_manager.provider_enabled(provider):
            continue

        reason = f"intent={intent}, priority={priority}, tier={tier}"
        if forced_route:
            reason += ", forced override"

        logger.debug("Route decision: provider=%s model=%s tier=%s intent=%s priority=%s forced=%s", provider, model, tier, intent, priority, forced_route)

        return RouteDecision(
            provider=provider,
            model=model,
            tier=tier,
            intent=intent,
            priority=priority,
            forced_route=forced_route,
            forced_provider=forced_provider,
            forced_model=forced_model,
            reason=reason,
        )

    raise ValueError("No viable provider/model found in fallback chain")
