from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ProviderBudget:
    enabled: bool = True
    daily_cost: float = 0.0
    monthly_cost: float = 0.0


class BudgetManager:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.providers: Dict[str, ProviderBudget] = {
            name: ProviderBudget(enabled=cfg.get("enabled", True))
            for name, cfg in config.get("providers", {}).items()
        }

    def provider_enabled(self, provider: str) -> bool:
        pb = self.providers.get(provider)
        return bool(pb and pb.enabled)

    def _cost_per_1k(self, provider: str, model: str) -> float:
        costs = self.config.get("budget", {}).get("cost_per_1k_tokens_usd", {}).get(provider, {})
        return costs.get(model, 0.5)  # fallback guess

    def _caps(self) -> Dict[str, float]:
        bcfg = self.config.get("budget", {})
        return {
            "monthly": float(bcfg.get("monthly_cap_per_provider_usd", 60.0)),
            "daily": float(bcfg.get("daily_cap_per_provider_usd", 2.0)),
        }

    def can_spend(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> bool:
        pb = self.providers.get(provider)
        if not pb or not pb.enabled:
            return False

        caps = self._caps()
        cost_per_1k = self._cost_per_1k(provider, model)

        total_tokens = prompt_tokens + completion_tokens
        est_cost = (total_tokens / 1000.0) * cost_per_1k

        if pb.daily_cost + est_cost > caps["daily"]:
            return False
        if pb.monthly_cost + est_cost > caps["monthly"]:
            return False
        return True

    def record_spend(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        pb = self.providers.get(provider)
        if not pb:
            return
        cost_per_1k = self._cost_per_1k(provider, model)
        total_tokens = prompt_tokens + completion_tokens
        est_cost = (total_tokens / 1000.0) * cost_per_1k
        pb.daily_cost += est_cost
        pb.monthly_cost += est_cost

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        return {
            provider: {
                "daily_cost_estimate": pb.daily_cost,
                "monthly_cost_estimate": pb.monthly_cost,
            }
            for provider, pb in self.providers.items()
        }
