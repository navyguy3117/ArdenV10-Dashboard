import os
from typing import Any, Dict

import yaml


CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs", "router.yaml")


def load_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
