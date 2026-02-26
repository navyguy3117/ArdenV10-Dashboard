# Arden Avatar Regeneration Prompts
## How to Use
1. Open ChatGPT (GPT-4o with image generation)
2. Upload 2-3 of the reference photos of your wife
3. Say: "Use these reference photos for the face/likeness in all the images I ask you to generate"
4. Then paste each prompt below, one at a time
5. Save outputs as the filenames listed (replacing existing files)

## Style Baseline (paste this FIRST after uploading reference photos)
```
I need you to generate a series of AI avatar portraits for a dashboard application.
The character is "Arden" - an autonomous AI agent. Use my wife's face/likeness from
the reference photos as the base for every image.

CONSISTENT STYLE FOR ALL IMAGES:
- Cyberpunk/sci-fi portrait, shoulders-up circular avatar format
- Dark background (#001020 to #030810 gradient)
- Glowing cyan (#00f0ff) accent lighting, neon rim light on hair/face
- The subject should have a subtle holographic/digital quality
- Futuristic headset, earpiece, or neural-link style accessory
- Hair styled up or pulled back (can have cyberpunk color highlights)
- Clothing: dark tech-wear / high-collar jacket or bodysuit with cyan accents
- Square aspect ratio, high detail, portrait photography quality
- Subtle circuit-board or data-stream patterns in the background
- The overall vibe: professional AI operator, cyberpunk aesthetic
```

---

## IDLE State (10 variants) — Calm, neutral, ready
Save as: `idle-01.png` through `idle-10.png`

```
Generate a cyberpunk AI avatar portrait using my wife's likeness. IDLE/READY state:
- Expression: calm, confident, slight knowing smile
- Eyes: looking directly at camera, relaxed
- Lighting: steady cyan rim light, no urgency
- Background: dark with faint circuit grid pattern
- Mood: professional, poised, waiting for input
- Subtle holographic data streams floating nearby

Please generate [X] of 10. Make each slightly different (angle, lighting, expression nuance).
```

## HAPPY State (10 variants) — Pleased, mission success
Save as: `happy-01.png` through `happy-10.png`

```
Generate a cyberpunk AI avatar portrait using my wife's likeness. HAPPY/SUCCESS state:
- Expression: warm genuine smile, eyes bright and engaged
- Lighting: brighter cyan/teal glow, hints of warm gold mixed in
- Background: dark with celebratory particle effects or sparkle
- Mood: task completed successfully, satisfied, proud
- Optional: subtle green success indicators in the holographic elements
- Energy: positive, warm, approachable

Please generate [X] of 10. Make each slightly different.
```

## THINKING State (10 variants) — Processing, analyzing
Save as: `thinking-01.png` through `thinking-10.png`

```
Generate a cyberpunk AI avatar portrait using my wife's likeness. THINKING/PROCESSING state:
- Expression: focused, eyes slightly narrowed or looking to the side
- One eyebrow slightly raised in contemplation
- Lighting: pulsing/animated-feel cyan, maybe purple (#b060ff) accents
- Background: data streams, code fragments, holographic displays active
- Mood: deep in analysis, computing, working through a problem
- Optional: holographic HUD elements near the face showing data
- Energy: intense concentration, mental activity

Please generate [X] of 10. Make each slightly different.
```

## ALERT State (10 variants) — Warning, attention needed
Save as: `alert-01.png` through `alert-10.png`

```
Generate a cyberpunk AI avatar portrait using my wife's likeness. ALERT/WARNING state:
- Expression: serious, alert, eyebrows slightly furrowed
- Eyes: wide and attentive, looking directly at viewer
- Lighting: amber/orange (#ff9900) warning tones mixed with cyan
- Background: dark with caution/warning holographic indicators
- Mood: something important needs attention, heightened awareness
- Optional: amber alert symbols or exclamation marks in holographic overlays
- Energy: urgent but controlled, professional concern

Please generate [X] of 10. Make each slightly different.
```

## ERROR State (10 variants) — Critical issue, system problem
Save as: `error-01.png` through `error-10.png`

```
Generate a cyberpunk AI avatar portrait using my wife's likeness. ERROR/CRITICAL state:
- Expression: concerned, tense, slight frown
- Eyes: intense, focused on the problem
- Lighting: red (#ff3355) danger tones dominating, cyan reduced
- Background: dark with glitch effects, red warning symbols, static
- Mood: critical system error, something has gone wrong
- Optional: cracked holographic displays, red error codes floating
- Slight digital distortion/glitch effect on edges of the portrait
- Energy: high tension, crisis mode

Please generate [X] of 10. Make each slightly different.
```

## BORED State (10 variants) — Low activity, waiting
Save as: `bored-01.png` through `bored-10.png`

```
Generate a cyberpunk AI avatar portrait using my wife's likeness. BORED/IDLE-LOW state:
- Expression: slightly disinterested, maybe resting chin on hand
- Eyes: half-lidded or looking away, relaxed to the point of boredom
- Lighting: dimmer cyan, desaturated, low energy
- Background: dark, minimal activity, faded circuit patterns
- Mood: nothing happening, understimulated, waiting for something interesting
- Optional: holographic elements powered down or in standby mode
- Energy: low, sleepy, "give me something to do"

Please generate [X] of 10. Make each slightly different.
```

---

## After Generation
Once you have all 60 images, save them to:
`\\wsl.localhost\Ubuntu-24.04\home\mikegg\.openclaw\workspace\avatars\`

Replace the existing files with matching filenames (idle-01.png, happy-01.png, etc.)
The dashboard will automatically pick them up on next avatar cycle.
