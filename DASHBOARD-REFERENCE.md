# ARDEN // COMMAND CENTER — Technical Reference

> **For:** Arden (Autonomous Intelligence v2.0)
> **Last Updated:** 2026-02-26
> **Version:** 1.2.0
> **Author:** Claude Opus (build partner)

Use this document to troubleshoot the Command Center dashboard. It covers every endpoint, every tile, every function, and every config value.

---

## Quick Troubleshooting Index

| Problem | Jump To |
|---------|---------|
| Dashboard won't load | [Startup & Server](#startup--server) |
| Tiles in wrong position | [Grid Layout](#grid-layout--tiles) |
| WebSocket disconnected | [WebSocket Events](#websocket-events) |
| API key not working | [Provider Config](#provider-configuration) |
| Chat not responding | [Chat Proxy](#chat-proxy) |
| Avatar stuck on one mood | [Avatar System](#avatar-system) |
| LM Studio shows offline | [LM Studio / LM Network](#lm-studio--lm-network) |
| Budget numbers wrong | [Budget Management](#budget-management) |
| Upload failing | [File Upload](#file-upload) |
| Login wall showing | [Authentication](#authentication--security) |
| Tiles not floating up on collapse | [Collapse Behavior](#collapse-float-up-behavior) |
| Cortex offline / memories not saving | [Cortex Memory Pipeline](#cortex-memory-pipeline-ardens-long-term-memory) |
| Observer snapshot not working | [Observer](#observer-ardens-eyes) |

---

## Architecture Overview

```
Browser (index.html)
    |
    |--- HTTP REST (/api/*) ---> FastAPI (main.py, port 3000)
    |--- WebSocket (/ws)    --->    |
    |                               |--- database.py (SQLite)
    |                               |--- metrics.py  (psutil + nvidia-smi)
    |                               |--- avatar.py   (mood engine + image rotation)
    |                               |
    |                               |--- External APIs:
    |                               |     Anthropic, OpenAI, OpenRouter
    |                               |     LM Studio (localhost:1234)
    |                               |     LM Network (10.10.10.180:1234)
    |                               |     Telegram Bot API
    |                               |
    |                               |--- Cortex Memory (10.10.10.180:3100):
    |                                     POST /api/memory/ingest  (conversations → long-term memory)
    |                                     GET  /api/memory/digest   (daily memory review)
    |                                     6 agents: Secretary, Arden, Lyra, Researcher, Sentinel, Opus
    |                                     Hybrid RAG: vector + FTS5 + recency
```

**Stack:** FastAPI + vanilla JS + GridStack.js + SQLite
**Server:** WSL2 Ubuntu-24.04, venv at `command_center/venv/`
**Launch:** `venv/bin/python main.py` or `systemctl --user start arden-command-center`

---

## File Paths

| Path | Purpose |
|------|---------|
| `/home/mikegg/.openclaw/workspace/` | Root workspace |
| `command_center/main.py` | Backend server (FastAPI) |
| `command_center/database.py` | SQLite ORM |
| `command_center/metrics.py` | System metrics collector |
| `command_center/avatar.py` | Avatar mood engine |
| `command_center/static/index.html` | Entire frontend (CSS + HTML + JS) |
| `command_center/.env` | Environment config |
| `command_center/command_center.db` | SQLite database |
| `avatars/` | Avatar PNG images (6 moods x N variants) |
| `imports/uploaded-docs/` | Uploaded files |
| `tasks/` | Task .txt/.md files |
| `arden/knowledge/` | Arden's self-written digest MDs (from Cortex) |
| `imports/observer/` | Observer snapshots, layout.json, summary.txt |
| `quick_launch.json` | Quick launch button config |
| `/home/mikegg/.openclaw/openclaw.json` | Master config (API keys, Telegram token) |

---

## Startup & Server

### Starting the Server

```bash
# Manual start
cd ~/.openclaw/workspace/command_center
venv/bin/python main.py

# Or via systemd
systemctl --user start arden-command-center
systemctl --user status arden-command-center

# Check logs
journalctl --user -u arden-command-center -f
# Or if launched manually:
cat /tmp/cc.log
```

### If Port 3000 is Busy

```bash
fuser -k 3000/tcp    # kill whatever's on port 3000
sleep 1
venv/bin/python main.py
```

### Environment Variables (.env)

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `3000` | Server port |
| `WORKSPACE_DIR` | `/home/mikegg/.openclaw/workspace` | Root workspace |
| `AVATARS_DIR` | `{WORKSPACE}/avatars` | Avatar images |
| `UPLOADS_DIR` | `{WORKSPACE}/imports/uploaded-docs` | Upload destination |
| `TASKS_DIR` | `{WORKSPACE}/tasks` | Task files |
| `DB_PATH` | `{WORKSPACE}/command_center.db` | SQLite database |
| `QUICK_LAUNCH_JSON` | `{WORKSPACE}/quick_launch.json` | Quick launch buttons |
| `OPENCLAW_JSON` | `/home/mikegg/.openclaw/openclaw.json` | Master config |
| `LM_STUDIO_URL` | `http://localhost:1234` | LM Studio base URL |
| `LOG_LEVEL` | `INFO` | Logging level |
| `MONTHLY_BUDGET` | `60.0` | Monthly spend limit (USD) |
| `CORTEX_URL` | `http://10.10.10.180:3100` | Arden's Cortex memory system |
| `GIPHY_API_KEY` | *(optional)* | Giphy search API |
| `CC_PASSWORD` | *(empty = auth disabled)* | Login wall password |
| `CC_SECRET` | *(auto-generated)* | JWT signing key |
| `CC_TOKEN_HOURS` | `24` | Token TTL in hours |
| `MAX_UPLOAD_MB` | `100` | Max upload size in MB |

---

## Authentication & Security

### Login Wall

Auth is **opt-in**. To enable:

```bash
# In command_center/.env
CC_PASSWORD=your-secure-password
```

Restart the server. The dashboard will show a cyberpunk login screen. Without `CC_PASSWORD`, everything is open (local dev mode).

### How Auth Works

1. User enters password on login screen
2. `POST /api/auth/login` validates password, returns JWT token
3. Token stored as `cc_token` httpOnly cookie
4. All API requests checked by auth middleware
5. WebSocket passes token via `?token=` query param

### Auth Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/auth/login` | Login (payload: `{password}`) |
| `GET` | `/api/auth/check` | Check if authenticated |
| `POST` | `/api/auth/logout` | Clear auth cookie |

### Public Paths (skip auth)

- `/` (frontend HTML)
- `/static/*` (CSS/JS assets)
- `/avatars/*` (avatar images)
- `/api/auth/*` (login/check/logout)

### Other Security

| Feature | Details |
|---------|---------|
| **CORS** | Locked to `localhost:3000` and `127.0.0.1:{PORT}` |
| **Security Headers** | X-Frame-Options: DENY, X-Content-Type-Options: nosniff, X-XSS-Protection, Referrer-Policy, Permissions-Policy |
| **Rate Limiting** | Chat: 15/min, Upload: 10/min, Command: 20/min |
| **Upload Validation** | 100MB max, extension whitelist, filename sanitization |
| **SQL Injection** | Parameterized queries throughout |
| **Path Traversal** | Filenames stripped of `/\` characters |

### Allowed Upload Extensions

`.pdf .txt .csv .json .md .yaml .yml .toml .png .jpg .jpeg .gif .svg .webp .py .js .ts .html .css .sh .env .log .xml .zip .tar .gz`

---

## API Endpoints — Complete Reference

### System & Health

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/system` | System metrics (CPU, RAM, disk, network) |
| `GET` | `/api/gpu` | NVIDIA GPU metrics |
| `GET` | `/api/system/local-pc` | Windows host metrics (via powershell) |

### Agents

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/agents` | List all agents |
| `POST` | `/api/agents/register` | Register/upsert agent |
| `GET` | `/api/agents/{name}/logs` | Agent-specific logs (limit 20) |
| `POST` | `/api/agents/{name}/status` | Update agent status |

**Register payload:** `{name, display_name, status, last_action, metadata}`
**Status payload:** `{status, last_action}`

### Logs

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/logs` | Fetch logs (params: limit, level, agent) |
| `POST` | `/api/logs` | Add log entry |
| `DELETE` | `/api/logs` | Clear all logs |

### Routing & Cost Tracking

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/routing` | Recent routing calls (limit 50) |
| `POST` | `/api/routing` | Log routing call (auto-calculates cost) |
| `GET` | `/api/routing/stats` | Per-provider stats |

**Routing payload:** `{provider, model_name, agent_name, tokens_in, tokens_out, cost_usd, latency_ms, actual_model}`

### Budget

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/budget` | Budget summary (spent, limit, remaining) |
| `PUT` | `/api/budget/config` | Set limits: `{monthly_limit, daily_limit}` |
| `GET` | `/api/budget/balances` | Provider bucket balances |
| `PUT` | `/api/budget/balance` | Set balance: `{provider, balance}` |

### Cron Jobs

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/crons` | List all cron jobs |
| `POST` | `/api/crons` | Register new cron |
| `POST` | `/api/crons/{name}/trigger` | Manually trigger job |

### Avatar

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/avatar` | Current avatar state (mood, image URL) |
| `POST` | `/api/avatar/reload` | Rescan avatar directory |
| `POST` | `/api/avatar/cycle` | Force image rotation |

### Chat & Commands

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/chat` | Chat proxy to AI providers |
| `POST` | `/api/command` | Execute dashboard command |

### Files & Uploads

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/upload` | Upload file (multipart) |
| `GET` | `/api/uploads` | Recent uploads (limit 10) |

### Tasks

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/tasks` | List all tasks |
| `POST` | `/api/tasks/create` | Create task: `{title, content}` |
| `DELETE` | `/api/tasks/{filename}` | Delete task file |
| `PUT` | `/api/tasks/{filename}/done` | Mark task done |
| `GET` | `/api/tasks/open-folder` | Open tasks folder in explorer |

### Notes

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/notes` | Get notes content |
| `POST` | `/api/notes` | Save notes: `{content, export_to_import}` |

### Providers

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/providers` | Provider list with key status |
| `GET` | `/api/lmstudio` | LM Studio status |
| `GET` | `/api/lmstudio/models` | List LM Studio models |
| `POST` | `/api/lmstudio/load` | Load model: `{model: "id"}` |
| `POST` | `/api/lmstudio/unload` | Unload model: `{instance_id: "id"}` |

### Telemetry (SSE)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/telemetry/overview` | Severity, budgets, jobs |
| `GET` | `/api/telemetry/providers` | Per-provider detailed stats |
| `GET` | `/api/telemetry/system/local` | Windows host metrics |
| `GET` | `/api/telemetry/system/agent` | WSL2 system metrics |
| `GET` | `/api/telemetry/stream` | SSE real-time telemetry stream |

### Cortex Memory (Arden's Long-Term Memory)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/cortex/ingest` | Manually flush buffered conversations to Cortex |
| `GET` | `/api/cortex/digest` | Fetch Arden's memory digest (?since=ISO, ?write=true) |
| `GET` | `/api/cortex/status` | Cortex health, buffer count, memory stats, knowledge files |

### Misc

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/quicklaunch` | Quick launch buttons |
| `GET` | `/api/telegram` | Telegram bot status |
| `GET` | `/api/giphy/search` | Proxy Giphy search: `?q=&limit=&offset=` |

---

## WebSocket Events

**Connection:** `ws://localhost:3000/ws` (or `ws://localhost:3000/ws?token=JWT` if auth enabled)

### Events Received by Frontend

| Event Type | Interval | Data |
|------------|----------|------|
| `init` | on connect | Full state: agents, logs, budget, routing, crons, avatar, lmstudio, telegram, tasks, uploads, notes, quicklaunch, providers |
| `system_metrics` | 5s | CPU, RAM, disk, network, GPU, uptime |
| `local_pc_metrics` | 10s | Windows CPU%, RAM%, temp |
| `avatar_update` | 10s | mood, image, color, image_url, all_images |
| `lmstudio_update` | 12s | online, model, loaded_models, all_models, vram |
| `lmnet_update` | 15s | LM Network status (RTX 4090 node) |
| `telegram_update` | 30s | connected, username, messages_today |
| `quicklaunch_update` | 5s | Array of quick launch buttons |
| `agent_update` | on change | Array of all agents |
| `activity_tick` | 5s | Latest activity entry |
| `tasks_update` | 60s | Array of task objects |
| `new_log` | on event | Single log entry |
| `logs_cleared` | on event | `{}` |
| `routing_call` | on event | Routing call record |
| `budget_update` | on event | Budget summary |
| `cron_update` | on event | Array of cron jobs |
| `upload_complete` | on event | Upload record |

### Events Sent by Frontend

| Event | Data |
|-------|------|
| `ping` | `{}` — server responds with `pong` |

---

## Grid Layout & Tiles

**Grid:** 12 columns, 55px row height, `float: true`, `margin: 4px`

### All 16 Tiles — Default Positions

| gs-id | x | y | w | h | Panel Content |
|-------|---|---|---|---|---------------|
| `avatar` | 0 | 0 | 3 | 12 | Arden avatar, mood, status, system gauges, tasks |
| `aicore` | 3 | 0 | 5 | 12 | Providers diagram, health gauges, budget, savings, manual reconcile |
| `routing` | 8 | 0 | 4 | 6 | Routing Monitor — live API call log |
| `jobs` | 8 | 6 | 4 | 6 | Active Jobs — cron job status |
| `lmstudio` | 0 | 12 | 3 | 8 | LM Studio (local) — model list, load/eject, GPU stats |
| `crons` | 3 | 12 | 3 | 8 | Scheduler — cron jobs with trigger buttons |
| `logs` | 6 | 12 | 3 | 8 | Live Logs — ALL/OK/WARN/ERR filters |
| `agents` | 9 | 12 | 3 | 8 | Agent Registry — status of all registered agents |
| `media` | 0 | 20 | 4 | 8 | Media Player — YouTube/Twitch/TikTok/Spotify/SoundCloud |
| `giphy` | 4 | 20 | 3 | 8 | Giphy — GIF search (needs GIPHY_API_KEY) |
| `notes` | 7 | 20 | 5 | 8 | Quick Notes — auto-save, SAVE button, + TASK |
| `arden-chat` | 0 | 28 | 5 | 14 | Arden Neural Link — direct chat, upload zone |
| `sessions` | 5 | 28 | 3 | 14 | Sessions — save/load chat sessions |
| `chat` | 8 | 28 | 4 | 14 | API Direct — multi-tab chat (Main/Scripting/Infra/Creative/Scratchpad) |
| `lmstudio-net` | 4 | 42 | 4 | 10 | LM Network // 4090 — remote Proxmox node, models, GPU |
| `rightpanel` | 0 | 42 | 4 | 7 | Context Panel — Telegram, Provider Registry, Active Channel |

### Collapse Float-Up Behavior

When you collapse a tile (click ▼ button), tiles below it **float up** to fill the gap. When you expand, they **push back down**. This uses a temporary `float:false` compaction followed by `float:true` for manual positioning.

### Resetting Layout

Click **RESET TILES** in the header bar, or run:
```javascript
resetGridLayout();
```

Layout is saved to `localStorage('cc-grid-layout')`. Collapse states saved to `localStorage('cc-tile-states')`.

---

## Chat Proxy

### Endpoint: `POST /api/chat`

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "messages": [{"role": "user", "content": "Hello"}],
  "agent_name": "chat",
  "api_key": "(optional — reads from env/openclaw.json if omitted)"
}
```

### Response:
```json
{
  "reply": "Hello! How can I help?",
  "model": "claude-sonnet-4-6",
  "tokens_in": 12,
  "tokens_out": 8
}
```

### Supported Providers

| Provider | API URL | Key Source |
|----------|---------|-----------|
| `anthropic` | `https://api.anthropic.com/v1/messages` | `ANTHROPIC_API_KEY` or openclaw.json |
| `openai` | `https://api.openai.com/v1/chat/completions` | `OPENAI_API_KEY` or openclaw.json |
| `openrouter` | `https://openrouter.ai/api/v1/chat/completions` | `OPENROUTER_API_KEY` or openclaw.json |
| `local` | `{LM_STUDIO_URL}/v1/chat/completions` | No key needed |

### Model Cost Rates (per 1M tokens: input/output)

**Anthropic:**
- claude-sonnet-4-5/4-6: $3.00 / $15.00
- claude-haiku-4-5: $0.80 / $4.00
- claude-3-opus: $15.00 / $75.00

**OpenAI:**
- gpt-4o: $2.50 / $10.00
- gpt-4o-mini: $0.15 / $0.60
- gpt-4.1: $2.00 / $8.00
- o3-mini: $1.10 / $4.40

**OpenRouter:** varies by model (check dashboard)

### Troubleshooting Chat

- **"No API key found"** → Check `openclaw.json` or set env var
- **Timeout** → Increase `aiohttp` timeout (default 120s)
- **429 rate limit** → Built-in rate limit: 15 requests/min per IP
- **Cost not tracking** → Model name must match `_MODEL_COSTS` dict in main.py

---

## Command Execution

### Endpoint: `POST /api/command`

**Command bar** is at the bottom of the dashboard: `ARDEN > command`

| Command | Syntax | What It Does |
|---------|--------|-------------|
| Trigger job | `trigger health_check` | Manually runs a cron job |
| Restart agent | `restart claude_agent` | Sets agent status to idle |
| Run agent | `run claude_agent analyze logs` | Dispatches agent with prompt |
| Clear logs | `clear logs` | Wipes all log entries |
| Reload avatars | `reload avatars` | Rescans avatar directory for new images |
| Set budget | `set budget 80` | Sets monthly limit to $80 |

---

## Avatar System

### Mood States

| Mood | Trigger | Color | Status Display |
|------|---------|-------|----------------|
| `idle` | Default / fallback | `#00f0ff` (cyan) | NOMINAL |
| `happy` | CPU < 50%, budget < 30%, no errors | `#00ff88` (green) | HAPPY |
| `thinking` | Agent processing | `#aa88ff` (purple) | FOCUSED |
| `bored` | Idle > 10 minutes | `#6080a0` (gray) | BORED |
| `alert` | CPU > 75% OR RAM > 75% OR budget > 60% | `#ffaa00` (amber) | ELEVATED |
| `error` | CPU > 90% OR RAM > 90% OR budget > 85% OR recent errors | `#ff3355` (red) | CRITICAL |

### Image Files

Located in `~/.openclaw/workspace/avatars/`

**Naming pattern:** `{mood}-{variant}.png`
- `idle-1.png`, `idle-2.png`, ... `idle-10.png`
- `happy-1.png`, `happy-2.png`, ...
- `thinking-1.png`, `alert-1.png`, `error-1.png`, `bored-1.png`

**Rotation:** Every 30 seconds, cycles to next variant within current mood. On mood change, immediately switches to matching prefix.

### Troubleshooting Avatar

- **Stuck on one image** → Run `reload avatars` command or `POST /api/avatar/reload`
- **Wrong mood** → Check system metrics (CPU/RAM thresholds trigger moods)
- **No image loading** → Check `avatars/` directory has PNG files with correct prefixes
- **New images not showing** → Reload avatars, or restart server

---

## LM Studio / LM Network

### LM Studio (Local)

- **URL:** `http://localhost:1234` (configurable via `LM_STUDIO_URL`)
- **Fallback URLs:** `http://10.10.10.98:1234`, WSL gateway
- **Polled:** Every 12 seconds

### LM Network (RTX 4090 / Proxmox)

- **URL:** `http://10.10.10.180:1234`
- **GPU:** RTX 4090
- **Node:** Proxmox server
- **Polled:** Every 15 seconds

### LM Studio API Calls

| Action | Endpoint | Payload |
|--------|----------|---------|
| List models | `GET /api/v0/models` | — |
| Load model | `POST /api/v1/models/load` | `{"model": "model-id"}` |
| Unload model | `POST /api/v1/models/unload` | `{"instance_id": "instance-id"}` |

### GPU Monitoring

nvidia-smi is queried every 5 seconds:
```bash
nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader,nounits
```

Paths tried: `/usr/lib/wsl/lib/nvidia-smi`, `nvidia-smi`, `/usr/bin/nvidia-smi`

### Troubleshooting LM Studio

- **Shows OFFLINE** → Is LM Studio actually running? Check `curl http://localhost:1234/api/v0/models`
- **Models not loading** → Check VRAM availability, model file integrity
- **GPU stats missing** → Is nvidia-smi available? Run it manually to test
- **LM Network offline** → Check Proxmox node at `10.10.10.180`, verify LM Studio is running there

---

## Budget Management

### How Costs Are Tracked

1. Every `POST /api/chat` call calculates cost using `_MODEL_COSTS` lookup
2. Cost = `(tokens_in * input_rate + tokens_out * output_rate) / 1_000_000`
3. Routing call logged to `routing_calls` table
4. Budget period = current month (resets on 1st)

### Manual Reconcile

The AI Core tile has a "MANUAL RECONCILE" section:
- Set monthly limit via `MONTHLY LIMIT` input + SET button
- Save actual provider balances (OpenRouter, OpenAI, Anthropic, Gemini, Local LM)
- Each row has a SAVE button that calls `PUT /api/budget/balance`

### Savings Tracking

The "SAVINGS — LOCAL LM" section shows:
- `SAVED MTD` / `SAVED ALL TIME` — money saved by using local models
- `LOCAL CALLS MTD` / `LOCAL TOKENS MTD` — local model usage
- Calculated as: `local_tokens * $1.00-$3.00 per 1M tokens` (cloud equivalent)

---

## Database Schema

**SQLite** at `{WORKSPACE}/command_center.db`

### Tables

**agents** — Registered AI agents
```sql
id INTEGER PRIMARY KEY, name TEXT UNIQUE, display_name TEXT,
status TEXT DEFAULT 'idle', last_action TEXT,
last_active TIMESTAMP, registered_at TIMESTAMP, metadata TEXT (JSON)
```

**logs** — System log entries
```sql
id INTEGER PRIMARY KEY, timestamp TIMESTAMP, agent_name TEXT DEFAULT 'system',
level TEXT DEFAULT 'INFO', message TEXT NOT NULL
```

**routing_calls** — API call history with cost tracking
```sql
id INTEGER PRIMARY KEY, timestamp TIMESTAMP, provider TEXT NOT NULL,
model_name TEXT, actual_model TEXT, agent_name TEXT DEFAULT 'unknown',
tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, latency_ms INTEGER
```

**budget** — Monthly spend tracking per provider
```sql
id INTEGER PRIMARY KEY, period_start DATE, provider TEXT,
total_spent REAL DEFAULT 0.0, UNIQUE(period_start, provider)
```

**budget_config** — Budget limits
```sql
monthly_limit REAL DEFAULT 60.0, daily_limit REAL DEFAULT 5.0
```

**cron_jobs** — Scheduled jobs
```sql
name TEXT UNIQUE, schedule TEXT (cron format), description TEXT,
last_run TIMESTAMP, next_run TIMESTAMP, last_status TEXT, run_count INTEGER, command TEXT
```

**notes** — Quick notes content
```sql
content TEXT, updated_at TIMESTAMP
```

**uploads** — File upload records
```sql
filename TEXT, original_name TEXT, size INTEGER, timestamp TIMESTAMP, path TEXT
```

**provider_balances** — Manual balance tracking
```sql
provider TEXT PRIMARY KEY, balance REAL, updated_at TIMESTAMP
```

---

## Background Tasks

These run continuously while the server is alive:

| Task | Interval | Purpose |
|------|----------|---------|
| `metrics_broadcaster` | 5s | CPU, RAM, disk, network, GPU metrics |
| `local_pc_broadcaster` | 10s | Windows host metrics via PowerShell |
| `avatar_updater` | 10s | Mood calculation + image rotation |
| `lmstudio_poller` | 12s | LM Studio model status |
| `lmnet_poller` | 15s | LM Network (4090) status |
| `telegram_poller` | 30s | Telegram bot connection check |
| `quicklaunch_watcher` | 5s | Reload quick_launch.json |
| `heartbeat_checker` | 30s | Timeout agents idle > 2 min |
| `budget_reset_checker` | 1h | Broadcast budget updates |
| `activity_ticker` | 5s | Broadcast last activity |
| `tasks_periodic` | 60s | Broadcast task list |
| `observer_file_writer` | 30s | Write layout.json + summary.txt to observer dir |
| `cortex_ingest_sender` | 4h | Flush buffered Neural Link conversations to Cortex |
| `cortex_nightly_digest` | 1 AM UTC | Fetch daily memory digest, write knowledge MDs |
| Watchdog | realtime | File changes in tasks/ directory |

---

## Frontend Functions Reference

### Core

| Function | Purpose |
|----------|---------|
| `initWS()` | Initialize WebSocket (auto-reconnect on close) |
| `handleEvent(type, data)` | Route incoming WS events to renderers |
| `tickClock()` | Update header clock every second |

### Rendering

| Function | Purpose |
|----------|---------|
| `renderHealth(m)` | System gauges (CPU, RAM, disk, GPU) |
| `renderLocalPC(d)` | Windows host metrics |
| `renderProviderNodes(stats)` | Provider activity circles |
| `renderBudget(d)` | Budget bar, spent/limit/remaining |
| `renderRouting(calls)` | Routing call list |
| `renderCrons(crons)` | Cron job list |
| `renderAgents(agents)` | Agent registry |
| `renderLogs()` | Log entries with filter |
| `renderTasks(tasks)` | Task list |
| `renderAvatar(a)` | Avatar image + mood + status |
| `renderLMStudio(d)` | LM Studio panel |
| `renderLMNet(d)` | LM Network panel |
| `renderTelegram(d)` | Telegram status |
| `renderRegistry(reg)` | Provider key registry |
| `renderUploads(uploads)` | Upload file list |

### User Actions

| Function | Purpose |
|----------|---------|
| `sendArdenMsg()` | Send message in Arden Neural Link |
| `clearArdenChat()` | Clear Arden chat history |
| `sendChat()` | Send message in API Direct |
| `saveCurrentSession()` | Save current chat to Sessions |
| `toggleCollapse(id)` | Collapse/expand tile (with float-up) |
| `toggleZoneB()` | Show/hide media row tiles |
| `resetGridLayout()` | Reset all tiles to default positions |
| `setLogFilter(level)` | Filter logs by level |
| `triggerCron(name)` | Manually trigger cron job |
| `saveBudgetBalance(provider)` | Save manual balance entry |
| `setBudgetLimit()` | Set monthly budget limit |
| `saveNotes()` | Save notes content |
| `exportNotes()` | Export notes to import folder |
| `createTaskFromNote()` | Create task from notes input |

### LM Studio Controls

| Function | Purpose |
|----------|---------|
| `lmLoad()` | Load model in local LM Studio |
| `lmUnload()` | Unload model from local LM Studio |
| `lmnLoad()` | Load model in LM Network (4090) |
| `lmnUnload()` | Unload model from LM Network |

### File Upload

| Function | Purpose |
|----------|---------|
| `ardenUploadFile(input)` | Upload file via Arden tile upload zone |
| `ardenHandleDrop(files)` | Handle drag-and-drop files |

### Navigation

| Function | Purpose |
|----------|---------|
| ARDEN button | `scrollIntoView` to arden-chat tile |
| LMN button | `scrollIntoView` to lmstudio-net tile |
| ZONE button | Toggle Zone B tile visibility |

---

## Cron Jobs (Default)

| Job | Schedule | Description |
|-----|----------|-------------|
| `budget_report` | `0 0 * * 1` | Weekly budget report (Mondays) |
| `cache_cleanup` | `0 */4 * * *` | Clear expired cache (every 4h) |
| `daily_summary` | `0 8 * * *` | Daily activity summary (8 AM) |
| `health_check` | `*/10 * * * *` | System health check (every 10min) |
| `memory_consolidate` | `0 2 * * *` | Consolidate agent memory (2 AM) |

---

## Telegram Integration

### Setup

Bot token is read from `openclaw.json`:
```json
{
  "channels": {
    "telegram": {
      "botToken": "123456:ABC..."
    }
  }
}
```

### Polling

Every 30 seconds, the server calls:
```
GET https://api.telegram.org/bot{token}/getMe
```

If successful: `connected: true`, `username: @Ardenv1_bot`
If failed: `connected: false`, `error: "..."``

---

## Troubleshooting Common Issues

### Dashboard shows blank / won't load
1. Is the server running? `curl http://localhost:3000/`
2. Check server logs: `cat /tmp/cc.log` or `journalctl --user -u arden-command-center`
3. Check port: `ss -tlnp | grep 3000`

### Tiles are jumbled / wrong positions
1. Click **RESET TILES** button in header
2. Or run in browser console: `resetGridLayout()`
3. Nuclear option: `localStorage.clear()` then refresh

### WebSocket keeps disconnecting
1. Check server is alive: `curl http://localhost:3000/api/system`
2. Check browser console for WS errors
3. WS auto-reconnects every 3 seconds
4. If auth enabled, make sure token hasn't expired (24h default)

### Chat returns error
1. Check API key: `curl http://localhost:3000/api/providers` — look for "present" vs "missing"
2. Check rate limit: max 15 chat requests/min
3. Check budget: if remaining < $0, requests may fail
4. Check model name matches provider's API

### Avatar stuck
1. Run command: `reload avatars`
2. Check avatars directory has properly named PNGs
3. Check mood logic: CPU/RAM/budget thresholds in avatar.py

### LM Studio / Network shows OFFLINE
1. Check LM Studio is actually running
2. Test connectivity: `curl http://localhost:1234/api/v0/models`
3. For LM Network: `curl http://10.10.10.180:1234/api/v0/models`
4. Check firewall isn't blocking the port

### Login wall won't go away
1. Make sure `CC_PASSWORD` in `.env` matches what you're typing
2. Clear cookies: browser DevTools > Application > Cookies > delete `cc_token`
3. To disable auth entirely: remove `CC_PASSWORD` from `.env` and restart

### Upload fails
1. Check file size < 100MB (configurable via `MAX_UPLOAD_MB`)
2. Check file extension is in whitelist
3. Check disk space: `df -h`
4. Check upload directory exists: `ls -la ~/.openclaw/workspace/imports/uploaded-docs/`

---

## Color Scheme Reference — "Electric Obsidian" (Arden Signature)

Updated 2026-02-26. Palette designed by Arden for her signature dashboard identity.

| Variable | Hex | Name | Usage |
|----------|-----|------|-------|
| `--cyan` | `#22D3EE` | Hyper-Cyan | Primary UI accent, general buttons, borders |
| `--violet` | `#8B5CF6` | Electric Ultraviolet | Active states, RouterCore, orbit rings, Arden panel signature |
| `--green` | `#34D399` | Neon Mint | Success, online, healthy |
| `--amber` | `#F59E0B` | Warm Amber | Warnings, info |
| `--red` | `#EF4444` | Soft Red | Errors, critical (softer than before) |
| `--purple` | `#8B5CF6` | Electric Ultraviolet | Info, thinking state |
| `--ember` | `#FB923C` | Soft Ember | Soft warnings, temperature |
| `--orange` | `#FB923C` | Soft Ember | Alert states |
| `--mag` | `#A78BFA` | Soft Violet | Secondary accent, user messages |
| `--blue` | `#60A5FA` | Sky Blue | Tertiary accent |
| `--text` | `#c8d8f0` | — | Foreground text |
| `--dim` | `#4a6080` | — | Muted/disabled text |
| `--bg` | `#0a0a0f` | Deep Obsidian | Main background |
| `--border` | `#1a2540` | — | Panel borders |

**Arden Panel Identity:** The Arden Neural Link panel uses `--violet` (#8B5CF6) exclusively for its glows, borders, labels, and accents. All other panels use `--cyan` (#22D3EE).

**Fonts:**
- Body: `"JetBrains Mono", "Fira Code", monospace` (12px)
- Headers/Titles: `"Orbitron", sans-serif`

---

## Dictation (Voice Input)

Both the Arden Neural Link and General Chat panels have microphone buttons for voice dictation.

**Requirements:** Chrome or Edge browser (uses Web Speech API / `webkitSpeechRecognition`). Must access dashboard via `localhost` (secure context required).

**How it works:**
- Click the 🎤 mic button next to SEND
- Button pulses violet with "LISTENING..." label when active
- Speech is transcribed in real-time (interim results shown in italic)
- Click again to stop
- Arden panel: `continuous: true` — keeps listening until you stop
- General Chat: `continuous: false` — stops after a pause

**Troubleshooting:**
- "Mic needs a secure context" → Open `http://localhost:3000` (not LAN IP)
- "Speech recognition not supported" → Use Chrome or Edge
- "Microphone access denied" → Allow mic permission in browser settings

---

## Observer (Arden's Eyes)

The Observer system gives Arden visual and spatial awareness of her own dashboard without relying on the user to describe it.

### How It Works

Two complementary systems:

1. **Pixel Snapshot (html2canvas)** — Captures a PNG screenshot of the dashboard as rendered in the browser. Saved to `workspace/imports/observer/current_view.png`. Triggered by clicking the 📷 camera button in the header bar (between RESET TILES and zoom controls).

2. **Layout Telemetry** — A JSON endpoint that returns the structural/spatial map of all tiles (positions, sizes, zones), system health, budget, tasks, agents, and more. Always available, no screenshot needed.

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/observer/snapshot` | `POST` | Receive base64 PNG from frontend, save to observer dir |
| `/api/observer/snapshot` | `GET` | Serve the latest saved screenshot as PNG |
| `/api/observer/snapshots` | `GET` | List available timestamped snapshots (last 20) |
| `/api/observer/trigger` | `POST` | Request a snapshot via WebSocket (browser must be open) |
| `/api/observer/layout` | `GET` | Full spatial + data map (tiles, system, budget, tasks, agents) |

### File-Based Access (No curl required)

The Observer writes files directly to `workspace/imports/observer/` that can be read from the filesystem:

| File | Updated | Description |
|---|---|---|
| `layout.json` | Every 30 seconds | Full layout + system data (same as `/api/observer/layout`) |
| `summary.txt` | Every 30 seconds | Plain-English dashboard state (theme, stats, GPU, budget, tasks, agents) |
| `current_view.png` | On each snapshot | Latest dashboard screenshot |
| `snapshot_status.json` | On each snapshot | Metadata about the last capture (timestamp, size, path) |

This is the **recommended access method** when HTTP/curl is unreliable. Just read the files directly.

### Triggering Snapshots Remotely

To request a screenshot without clicking the camera button:
```
curl -4 -X POST http://localhost:3000/api/observer/trigger
```
The backend sends a WebSocket event to the browser, which captures and saves the screenshot automatically. Check `snapshot_status.json` for confirmation.

If no browser is connected, the trigger returns `"status": "no_browser"` — use `layout.json` for data-only access.

### Snapshot Storage

- **Location:** `workspace/imports/observer/`
- **Latest:** `current_view.png` (always overwritten)
- **History:** `snapshot_YYYYMMDD_HHMMSS.png` (last 20 kept, older auto-purged)
- **Max size:** 10 MB per snapshot

### Camera Button (Header)

The 📷 button in the top header bar:
- **Idle:** Dim border, subtle icon
- **Capturing:** Pulses violet with "CAPTURING..." label and expanding ring animation
- **Success:** Briefly flashes green
- **Error:** Briefly flashes red

### Layout Map Fields

The `/api/observer/layout` response includes:
- `tiles[]` — ID, label, and zone for each panel
- `system` — CPU, RAM, GPU, disk, network I/O, uptime
- `budget` — Current spend, limit, remaining, per-provider breakdown
- `tasks[]` — Task filenames and content preview (first 500 chars)
- `agents[]` — Registered agents and their status
- `jobs[]` — Cron jobs and last run status
- `lmstudio` — LM Studio connection status and loaded models
- `snapshotAvailable` — Boolean, whether a screenshot exists
- `connectedBrowsers` — Number of browser tabs connected via WebSocket

### Usage Notes

- Snapshots only capture the dashboard page (`localhost:3000`). No access to browser tabs, desktop, or anything outside the page.
- The camera button only works when someone has the dashboard open in a browser.
- Layout telemetry is always available regardless of whether the browser is open.
- Arden reads these files/endpoints as reference only. All code changes go through Claude (vendor).

---

## Cortex Memory Pipeline (Arden's Long-Term Memory)

Arden's Cortex is a multi-agent RAG system running on the RTX 4090 box (`10.10.10.180:3100`). It gives Arden persistent memory across sessions — conversations are ingested, processed by 6 agents, stored in hybrid vector/keyword search, and periodically reviewed to generate self-knowledge files.

### Architecture

```
Arden Neural Link Chat
    |
    |--- User + Assistant messages captured to in-memory buffer
    |
    |--- cortex_ingest_sender (every 4 hours)
    |         |
    |         POST /api/memory/ingest  →  Cortex (10.10.10.180:3100)
    |                                        |
    |                                        |--- 6 agents process memories:
    |                                        |    Secretary (Nemo 12B local)
    |                                        |    Arden (Claude Sonnet)
    |                                        |    Lyra (GPT-4o)
    |                                        |    Researcher (Gemini Flash)
    |                                        |    Sentinel (Nemo 12B local)
    |                                        |    Opus (Claude Opus)
    |                                        |
    |                                        |--- Hybrid RAG storage:
    |                                             Vector cosine (0.7 weight)
    |                                             FTS5 keyword (0.3 weight)
    |                                             Recency boost
    |
    |--- cortex_nightly_digest (1:00 AM UTC / ~9 PM EST)
              |
              GET /api/memory/digest  →  Cortex
              |
              Writes:
                arden/knowledge/latest_digest.json
                arden/knowledge/digest_YYYY-MM-DD.md
```

### How It Works

1. **Capture:** Every Arden Neural Link conversation (user + assistant messages) is buffered in memory.
2. **Ingest:** Every 4 hours, buffered conversations are flushed to Cortex via `POST /api/memory/ingest`. Cortex processes them through its 6-agent pipeline and stores as episodic, semantic, or procedural memories.
3. **Nightly Digest:** At 1:00 AM UTC, the dashboard fetches Arden's accumulated memories via `GET /api/memory/digest`, then writes:
   - `latest_digest.json` — raw JSON for programmatic access
   - `digest_YYYY-MM-DD.md` — human-readable markdown grouped by memory type
4. **Context Injection:** Arden's system prompt is enriched with her latest digest memories and knowledge file references, so she's aware of what she's learned.

### Memory Types

| Type | Description |
|------|-------------|
| **Episodic** | Specific events and interactions (who said what, when) |
| **Semantic** | Factual knowledge and learned concepts |
| **Procedural** | How-to knowledge, processes, workflows |

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/cortex/ingest` | `POST` | Manually flush all buffered conversations to Cortex now |
| `/api/cortex/digest` | `GET` | Fetch memory digest. Params: `?since=ISO8601`, `?write=true` to also write knowledge MDs |
| `/api/cortex/status` | `GET` | Full status: Cortex health, buffer count, memory stats, knowledge files, last ingest/digest timestamps |

### File-Based Access

| File | Location | Description |
|---|---|---|
| `latest_digest.json` | `arden/knowledge/` | Latest full digest from Cortex (raw JSON) |
| `digest_YYYY-MM-DD.md` | `arden/knowledge/` | Daily knowledge digest in markdown format |

### Status Response Example

```json
{
  "cortex_url": "http://10.10.10.180:3100",
  "buffered_conversations": 0,
  "last_ingest": "2026-02-26T21:49:07.827210",
  "last_digest": "2026-02-26T21:50:51.439071",
  "cortex_health": "online",
  "memory_stats": { "total": 10, "episodic": 0, "semantic": 4, "procedural": 6 },
  "knowledge_files": 1,
  "latest_knowledge": "digest_2026-02-26.md"
}
```

### Troubleshooting

- **Cortex offline** → Check `10.10.10.180:3100` is reachable: `curl -4 http://10.10.10.180:3100/health`
- **Buffer not draining** → Manually flush: `curl -4 -X POST http://localhost:3000/api/cortex/ingest`
- **No knowledge files** → Manually trigger: `curl -4 "http://localhost:3000/api/cortex/digest?write=true"`
- **Conversations not buffering** → Ensure you're chatting through the Arden Neural Link panel (not General Chat)
- **Nightly digest not running** → Check server logs, confirm server hasn't restarted (timer resets on restart)

### Safety & Guardrails

- Arden can READ her knowledge files but does NOT modify dashboard code or config
- All code changes go through Claude (vendor) with Mike's (CEO) approval
- Cortex processes memories through multiple agents for quality — no single point of failure
- Buffer survives within a server session but not across restarts (conversations in buffer are lost on server restart)
- Failed ingests put conversations back in the buffer for retry

---

*End of reference. If something isn't covered here, check the source:*
- *Backend:* `command_center/main.py`
- *Frontend:* `command_center/static/index.html`
- *Database:* `command_center/database.py`
- *Metrics:* `command_center/metrics.py`
- *Avatar:* `command_center/avatar.py`
