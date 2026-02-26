import os
import math
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .logging_utils import log_context


def _approx_tokens_from_messages(messages: List[Any]) -> int:
    text = "\n".join(str(m.content) for m in messages)
    return max(1, len(text) // 4)


def _load_pins(pins_file: str) -> List[str]:
    if not os.path.exists(pins_file):
        return []
    with open(pins_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    return lines


def _summarize_if_needed(messages: List[Any], config: Dict[str, Any], priority: str) -> Tuple[List[Any], Dict[str, Any]]:
    """Placeholder for future internal summarizer calls.
    For now, we only do structural trimming and log what would happen.

    This is synchronous on purpose so that build_context can remain a normal
    function without requiring async/await plumbing.
    """
    tokens_before = _approx_tokens_from_messages(messages)
    tokens_after = tokens_before

    info = {
        "method": "keep",
        "input_tokens_before": tokens_before,
        "input_tokens_after": tokens_after,
        "pinned_included": True,
        "summarizer_tier_used": None,
        "summary_tokens_requested": 0,
    }

    return messages, info


def _ensure_summaries_dir(summaries_dir: str) -> None:
    os.makedirs(summaries_dir, exist_ok=True)


def build_context(req: Any, config: Dict[str, Any]) -> Tuple[List[Any], Dict[str, Any]]:
    """Build and trim context for a request.

    Rules (high-level):
    - Always preserve system messages and pinned memory.
    - Prefer recent conversation turns; drop oldest non-pinned first.
    - Respect token budgets from config: target + hard max.
    - If summarization is enabled in config, summarize older context into a
      compact system message (350–500 tokens target) and persist the summary
      under memory/router-summaries/YYYY-MM-DD.md.

    NOTE: Summarization is currently implemented as a no-op placeholder; this
    function is structured so a real summarizer can be dropped in later
    without changing the external behavior.
    """

    tokens_cfg = config.get("tokens", {})
    priorities_cfg = tokens_cfg.get("priorities", {})

    priority = (
        req.metadata.priority
        if req.metadata and getattr(req.metadata, "priority", None)
        else config.get("routing", {}).get("default_priority", "normal")
    )
    limits = priorities_cfg.get(
        priority,
        priorities_cfg.get("normal", {"target_input_tokens": 6000, "hard_max_input_tokens": 10000}),
    )

    target = limits.get("target_input_tokens", 6000)
    hard_max = limits.get("hard_max_input_tokens", 10000)

    pins_file = config.get("memory", {}).get("pins_file", "memory/pins.md")
    summaries_dir = config.get("memory", {}).get("summaries_dir", "memory/router-summaries")

    messages = list(req.messages)

    # Include pins as a synthetic system message (simple implementation)
    pins = _load_pins(pins_file)
    if pins:
        pinned_text = "\n".join(pins)
        from .main import ChatMessage  # local import to avoid circular

        messages.insert(0, ChatMessage(role="system", content=f"Pinned context:\n{pinned_text}"))

    # 1) Compute tokens before any trimming
    tokens_before = _approx_tokens_from_messages(messages)

    # 2) Drop oldest non-system (non-pinned) until under hard_max.
    #    System messages are always protected; pinned content is included in
    #    the synthetic system message above.
    trimmed = list(messages)

    def is_protected(msg: Any) -> bool:
        return msg.role == "system"

    while _approx_tokens_from_messages(trimmed) > hard_max and any(not is_protected(m) for m in trimmed):
        # drop the oldest non-system
        for idx, m in enumerate(trimmed):
            if not is_protected(m):
                trimmed.pop(idx)
                break

    # 3) Summarization placeholder (no external call yet; just logs "keep").
    #    In a fuller implementation, we'd call the cheapest summarizer tier
    #    here when tokens_before > target and write a summary to
    #    summaries_dir/YYYY-MM-DD.md.
    _ensure_summaries_dir(summaries_dir)
    trimmed, context_info = _summarize_if_needed(trimmed, config, priority)

    tokens_after = _approx_tokens_from_messages(trimmed)

    context_info.update(
        {
            "estimated_prompt_tokens_before": tokens_before,
            "estimated_prompt_tokens": tokens_after,
            "target_input_tokens": target,
            "hard_max_input_tokens": hard_max,
        }
    )

    log_context(context_info, config)

    return trimmed, context_info
