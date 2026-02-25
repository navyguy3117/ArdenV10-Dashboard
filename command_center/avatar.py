"""
avatar.py - Avatar mood state management and image cycling for Arden
Scans avatars directory, detects mood from system state, cycles images
"""
import os
import random
import time
from pathlib import Path
from typing import List, Optional, Dict
import logging

logger = logging.getLogger("command_center.avatar")

MOOD_PREFIXES = {
    "happy": "happy",
    "thinking": "thinking",
    "alert": "alert",
    "error": "error",
    "bored": "bored",
    "idle": "idle",
}

MOOD_COLORS = {
    "idle": "#00f0ff",
    "happy": "#00ff88",
    "thinking": "#aa88ff",
    "alert": "#ffaa00",
    "error": "#ff3355",
    "bored": "#6080a0",
}


class AvatarManager:
    def __init__(self, avatars_dir: str):
        self.avatars_dir = Path(avatars_dir)
        self._current_mood = "idle"
        self._current_image: Optional[str] = None
        self._last_cycle = 0.0
        self._cycle_interval = 30.0  # seconds
        self._images_by_mood: Dict[str, List[str]] = {}
        self._all_images: List[str] = []
        self.scan()

    def scan(self):
        """Scan avatar directory and categorize images by mood prefix."""
        self._images_by_mood = {mood: [] for mood in MOOD_PREFIXES}
        self._all_images = []

        if not self.avatars_dir.exists():
            logger.warning(f"Avatar directory not found: {self.avatars_dir}")
            return

        for f in sorted(self.avatars_dir.iterdir()):
            if f.suffix.lower() == ".png" and not f.name.endswith(":Zone.Identifier"):
                name = f.name
                self._all_images.append(name)
                matched = False
                for mood, prefix in MOOD_PREFIXES.items():
                    if name.lower().startswith(prefix + "-") or name.lower().startswith(prefix + "_"):
                        self._images_by_mood[mood].append(name)
                        matched = True
                        break
                if not matched:
                    # Uncategorized goes to idle
                    self._images_by_mood["idle"].append(name)

        logger.info(f"Loaded {len(self._all_images)} avatar images: {dict({k: len(v) for k, v in self._images_by_mood.items() if v})}")

        # Set initial image
        if not self._current_image:
            self._select_image()

    def determine_mood(
        self,
        cpu_percent: float = 0,
        memory_percent: float = 0,
        has_errors: bool = False,
        budget_percent: float = 0,
        minutes_since_activity: float = 0,
        processing: bool = False,
    ) -> str:
        """Determine mood state based on system metrics."""
        # Error state: critical metrics or agent errors
        if has_errors or cpu_percent > 90 or memory_percent > 90 or budget_percent > 85:
            return "error"

        # Alert state: warning thresholds
        if cpu_percent > 75 or memory_percent > 75 or budget_percent > 60:
            return "alert"

        # Thinking: currently processing
        if processing:
            return "thinking"

        # Bored: no activity for 10+ minutes
        if minutes_since_activity > 10:
            return "bored"

        # Happy: all systems green
        if cpu_percent < 50 and budget_percent < 30 and not has_errors:
            return "happy"

        return "idle"

    def _select_image(self, mood: str = None) -> Optional[str]:
        """Select an image for the given mood, with fallback chain."""
        target = mood or self._current_mood
        candidates = self._images_by_mood.get(target, [])

        if not candidates:
            # Fallback: try idle
            candidates = self._images_by_mood.get("idle", [])

        if not candidates:
            # Fallback: any image
            candidates = self._all_images

        if not candidates:
            self._current_image = None
            return None

        # Avoid repeating the same image if possible
        if len(candidates) > 1 and self._current_image in candidates:
            candidates = [c for c in candidates if c != self._current_image]

        self._current_image = random.choice(candidates)
        return self._current_image

    def update(
        self,
        cpu_percent: float = 0,
        memory_percent: float = 0,
        has_errors: bool = False,
        budget_percent: float = 0,
        minutes_since_activity: float = 0,
        processing: bool = False,
    ) -> Dict:
        """Update mood and optionally cycle image. Returns current state."""
        new_mood = self.determine_mood(
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            has_errors=has_errors,
            budget_percent=budget_percent,
            minutes_since_activity=minutes_since_activity,
            processing=processing,
        )

        mood_changed = new_mood != self._current_mood
        self._current_mood = new_mood

        # Cycle image every 30 seconds or on mood change
        now = time.time()
        if mood_changed or (now - self._last_cycle) >= self._cycle_interval:
            self._select_image(new_mood)
            self._last_cycle = now

        return self.get_state()

    def get_state(self) -> Dict:
        return {
            "mood": self._current_mood,
            "image": self._current_image,
            "color": MOOD_COLORS.get(self._current_mood, "#00f0ff"),
            "image_url": f"/avatars/{self._current_image}" if self._current_image else None,
            "all_images": self._all_images,
            "available_moods": {k: len(v) for k, v in self._images_by_mood.items() if v},
        }

    def force_cycle(self) -> Dict:
        """Force an immediate image cycle."""
        self._select_image()
        self._last_cycle = time.time()
        return self.get_state()

    def reload(self) -> Dict:
        """Rescan avatar directory."""
        self.scan()
        return self.get_state()
