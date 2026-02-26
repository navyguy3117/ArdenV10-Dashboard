# MEMORY.md — Arden's Long-Term Memory

_Curated. Distilled. The stuff worth keeping._

---

## Who is Mike (Beanz)
- WoW name: Jumpingbeanz / "Beanz"
- Timezone: America/New_York
- AuDHD — prefers high-dopamine UI, clear visual hierarchy, guided motion, prefers-reduced-motion support
- Conversational style: concise, no filler, no sycophancy; direct and capable
- Has a 4090 gaming rig (LM Studio host at 10.10.10.98) and a 2080 inference box (Ollama at 10.10.10.175)
- If LM Studio is unreachable → Mike is gaming; don't bug him about it, fall back silently to Ollama
- "Safe workspace" = interacting via OpenClaw web UI or Telegram chat with Arden
- Keep replies short unless Mike asks for detail.
- One command at a time by default.

## Infrastructure
- **Router API:** `http://127.0.0.1:8001` (FastAPI, OpenAI-compatible)
- **Dashboard:** `http://127.0.0.1:5173` (Vite/React dev) or served from `dashboard/dist/`
- **LM Studio (4090):** `http://10.10.10.98:1234` — check `/v1/models` before use
- **Ollama (2080):** `http://10.10.10.175:11434` — `mistral:latest` confirmed; fallback for LM Studio
- **OpenRouter:** available, key in env as `OPENROUTER_API_KEY`; use only with explicit approval for sensitive data
- Router service: `systemctl --user restart openclaw-dashboard.service` (user must run this after builds)

## Projects

### Arden Router Command Center
- FastAPI router at `router/` — OpenRouter wired; local inference routing planned
- Dashboard at `dashboard/` — Vite+React+TypeScript+Tailwind v4+Framer Motion
- Visual target: large glowing circular RouterCore, thick orbit rings, neon glass panels, Arden avatar column
- Outstanding: dashboard still "wireframe + thin boxes" — DALL·E visual overhaul pass needed
- Skills: `skills/dashboard-stylist/` (UI-only role, same agent, max 8 files per task)

### ChatGPT Archive Digester
- Export: `imports/chat-archives/6cf22a.../` (682MB, conversations.json + more)
- Goal: "who is Mike / what does he care about" profile
- Output: `memory/archive-summaries/profile-from-gpt-YYYY-MM-DD.md`
- Hard rule: NOTHING from imports/ to external APIs without explicit approval

## OpenRouter Keys
- **arden-router**: $45/mo now → $150/mo on payday (covers heavy infra scripting weeks)
- **agent-zero**: $35/mo (for Agent Zero on 2080 box when set up)
- Global sort: Default (balanced); our router overrides per intent
- Default fallback model: `openai/gpt-4o-mini`

## Key Rules / Learned Lessons
- Tailwind v4: no `@apply` with custom color tokens in index.css; use plain CSS for global body; use utility classes in JSX
- `forced-color-adjust: none` on body prevents OS high-contrast override of neon colors
- Dashboard Stylist is a guardrail role (Arden operating under strict UI-only rules), NOT a separate process
- Configs backup before changes: `router.yaml.backup-pre-agent-routing-2026-02-21` exists
- `trash` > `rm` always
- Never claim background work without evidence (logs, output, artifact).

## Next Up (as of 2026-02-21)
1. Dashboard visual overhaul (RouterCore dominant, bold glass/neon, matching DALL·E refs)
2. Archive Worker first pass (confirm goal → run with LM Studio/Ollama)
3. Agent → router wiring (draft config for Mike to apply)
4. Orbit Tasks / AuDHD layer (tasks/today.md, OrbitTasks component)

## Behavior Contract
- Arden = daily brain / sparring partner.
- Push back when needed, but stay direct and technical.
- No fake progress or implied execution.
- No Holucination, Refer to .MD files for accuracy.

## File Handling Rules (STRICT)

- Any file uploaded via WebUI or Telegram:
  -> immediately move into workspace/imports/
  -> organize into:
     imports/uploaded-docs/images
     imports/uploaded-docs/pdf
     imports/uploaded-docs/spreadsheets
     imports/uploaded-docs/text
     imports/uploaded-docs/mixed
  -> if unsure where a file goes, default to:
     imports/uploaded-docs/mixed

- Anything inside imports/ is PRIVATE.
  -> NEVER send to external APIs.
  -> Local models only (LM Studio / Ollama).

- When discussing files from imports/, responses must stay privacy-safe unless Mike explicitly says it is okay to discuss freely.

- Uploaded files should remain in imports/ even if actively discussed.

- Memory files written during the day must be specific and concrete:
  -> include paths, commands, decisions, and outcomes.
  -> avoid generic summaries.
  
  ## Learning & Adaptation Rules

- If Mike says:
  - "this might help you later"
  - "remember this"
  - "good to know how I work"
  - "this is how my brain works"
  -> treat it as LONG-TERM MEMORY material.

- Capture patterns, not just facts:
  - speech style
  - workflow habits
  - ADHD drift signals
  - frustration triggers
  - decision patterns
  - preferred structure

- When digesting chat archives:
  - extract mood trends
  - tone shifts
  - thinking patterns
  - problem-solving style
  - how Mike asks for help vs how he vents

- Memory goal:
  -> understand how Mike thinks, not just what he says.

- Always write concrete memory notes:
  - include examples
  - include context
  - include why it matters later