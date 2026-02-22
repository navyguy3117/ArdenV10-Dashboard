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

## Key Rules / Learned Lessons
- Tailwind v4: no `@apply` with custom color tokens in index.css; use plain CSS for global body; use utility classes in JSX
- `forced-color-adjust: none` on body prevents OS high-contrast override of neon colors
- Dashboard Stylist is a guardrail role (Arden operating under strict UI-only rules), NOT a separate process
- Configs backup before changes: `router.yaml.backup-pre-agent-routing-2026-02-21` exists
- `trash` > `rm` always

## Next Up (as of 2026-02-21)
1. Dashboard visual overhaul (RouterCore dominant, bold glass/neon, matching DALL·E refs)
2. Archive Worker first pass (confirm goal → run with LM Studio/Ollama)
3. Agent → router wiring (draft config for Mike to apply)
4. Orbit Tasks / AuDHD layer (tasks/today.md, OrbitTasks component)
