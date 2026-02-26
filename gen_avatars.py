#!/usr/bin/env python3
"""
Generate 5 avatar images per mood for Arden (30 total)
Using OpenAI DALL-E 3 API (stdlib urllib only, no extra deps needed)
Saves to /home/mikegg/.openclaw/workspace/avatars/{mood}-01.png through {mood}-05.png

Cost estimate: ~$0.04/image x 30 = ~$1.20 total (DALL-E 3 standard 1024x1024)
"""
import urllib.request
import urllib.error
import json
import os
import time

AVATAR_DIR = "/home/mikegg/.openclaw/workspace/avatars"
os.makedirs(AVATAR_DIR, exist_ok=True)

API_KEY = os.environ.get("OPENAI_API_KEY", "")
if not API_KEY:
    # Fall back to key stored in openclaw.json
    try:
        import json as _json
        with open("/home/mikegg/.openclaw/openclaw.json") as _f:
            _cfg = _json.load(_f)
        API_KEY = _cfg["skills"]["entries"]["openai-image-gen"]["apiKey"]
    except Exception:
        pass
if not API_KEY:
    raise SystemExit("ERROR: OPENAI_API_KEY not set and could not read from openclaw.json")

# Base style consistent across all moods
BASE_STYLE = (
    "anime AI assistant named Arden, female, cyberpunk aesthetic, "
    "short teal hair, glowing circuit tattoos, holographic HUD elements, "
    "sleek dark bodysuit, dark background with neon particles, "
    "high detail digital art, portrait, no watermark, no text"
)

MOODS = {
    "idle": {
        "desc": "calm neutral expression, soft cyan blue glowing eyes, relaxed pose, gentle cyan neon aura",
    },
    "happy": {
        "desc": "bright joyful smile, wide gleaming eyes, enthusiastic pose, warm green neon glow, cheerful expression",
    },
    "thinking": {
        "desc": "contemplative expression, finger on lips or chin, eyes looking up thoughtfully, ethereal purple neon glow, holographic data streams",
    },
    "alert": {
        "desc": "sharp focused attentive eyes wide open, alert stance, urgent expression, warm amber orange neon glow, warning indicators",
    },
    "error": {
        "desc": "concerned worried distressed expression, furrowed brow, tense look, crimson neon glow, glitch effect overlays",
    },
    "bored": {
        "desc": "drowsy uninterested expression, half-lidded eyes, slouched relaxed pose, cool slate blue neon glow, resting head on hand",
    },
}

# Variation hints to get distinct compositions across 5 images per mood
VARIATION_HINTS = [
    "close-up portrait framing",
    "three-quarter view, slight angle",
    "direct front-facing gaze",
    "looking slightly upward, dramatic lighting",
    "subtle side profile, atmospheric depth",
]


def generate_image(prompt: str, out_path: str) -> bool:
    """Generate a single image via OpenAI DALL-E 3 and save it."""
    payload = json.dumps({
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "quality": "standard",
        "response_format": "url",
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=payload,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read())
        img_url = result["data"][0]["url"]
        revised = result["data"][0].get("revised_prompt", "")
        if revised:
            short = revised[:80] + "..." if len(revised) > 80 else revised
            print(f"    (revised: {short})")

        # Download the generated image
        img_req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(img_req, timeout=60) as img_resp:
            img_data = img_resp.read()

        with open(out_path, "wb") as f:
            f.write(img_data)
        print(f"    ✓ Saved {len(img_data):,} bytes → {os.path.basename(out_path)}")
        return True

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        print(f"    ERROR HTTP {e.code}: {body}")
        return False
    except Exception as e:
        print(f"    ERROR: {e}")
        return False


def main():
    total = 0
    errors = 0

    for mood, cfg in MOODS.items():
        print(f"\n{'='*50}")
        print(f"MOOD: {mood.upper()}")
        print(f"{'='*50}")

        for i, hint in enumerate(VARIATION_HINTS, start=1):
            out_path = os.path.join(AVATAR_DIR, f"{mood}-{i:02d}.png")

            if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                print(f"  SKIP {mood}-{i:02d}.png (already exists, {os.path.getsize(out_path):,} bytes)")
                total += 1
                continue

            prompt = f"{BASE_STYLE}, {cfg['desc']}, {hint}"
            print(f"  [{i}/5] Generating {mood}-{i:02d}.png ...")

            ok = generate_image(prompt, out_path)
            if ok:
                total += 1
            else:
                errors += 1

            # Polite pause between requests (DALL-E 3: up to 5 img/min on Tier 1+)
            if i < len(VARIATION_HINTS):
                time.sleep(4)

        # Slightly longer pause between moods
        time.sleep(2)

    print(f"\n{'='*50}")
    print(f"DONE: {total} images saved, {errors} errors")
    print(f"Output: {AVATAR_DIR}")

    files = sorted(
        f for f in os.listdir(AVATAR_DIR)
        if f.endswith(".png") and not f.endswith(".Identifier")
    )
    print(f"\nAvatars directory ({len(files)} .png files):")
    for f in files:
        size = os.path.getsize(os.path.join(AVATAR_DIR, f))
        print(f"  {f}  ({size:,} bytes)")


if __name__ == "__main__":
    main()
