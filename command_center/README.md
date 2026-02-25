# Arden // Command Center

FastAPI dashboard for the OpenClaw instance. Served on **port 3000** from WSL2 Ubuntu 24.04. Real-time updates via WebSocket. SQLite persistence. All tiles are drag-and-resize via GridStack.js.

---

## Quick Start

```bash
# Check service status
systemctl --user status arden-command-center

# Restart after code changes
systemctl --user restart arden-command-center

# View live logs
journalctl --user -u arden-command-center -f

# Open in browser
http://localhost:3000
```

---

## File Structure

```
/home/mikegg/.openclaw/workspace/command_center/
├── main.py                       # FastAPI backend — all API routes, WebSocket, background pollers
├── database.py                   # SQLite helpers (agents, logs, routing, budget, crons, notes, uploads)
├── metrics.py                    # psutil system metrics collector
├── avatar.py                     # Avatar image manager (mood-to-image file matching)
├── requirements.txt              # Python dependencies
├── .env                          # Optional env overrides (see Configuration section)
├── static/
│   └── index.html                # Entire frontend — CSS + HTML + JS, fully self-contained
├── venv/                         # Python virtual environment
└── arden-command-center.service  # systemd user service file

/home/mikegg/.openclaw/workspace/
├── avatars/                      # Avatar images — mood-prefixed PNG/JPG files
├── imports/uploaded-docs/        # Files uploaded via Doc Drop Zone panel
├── tasks/                        # .txt/.md task files read by Task Queue panel
├── command_center.db             # SQLite database (auto-created on first run)
├── quick_launch.json             # Quick Launch button definitions (hot-reloaded every 5s)
└── openclaw.json                 # OpenClaw config — Telegram token read from here (never modified)
```

---

## Configuration

All settings live in `/home/mikegg/.openclaw/workspace/command_center/.env`.

| Variable | Default | Description |
|---|---|---|
| `WORKSPACE_DIR` | `/home/mikegg/.openclaw/workspace` | Root workspace path |
| `AVATARS_DIR` | `$WORKSPACE_DIR/avatars` | Avatar images directory |
| `UPLOADS_DIR` | `$WORKSPACE_DIR/imports/uploaded-docs` | File upload destination |
| `TASKS_DIR` | `$WORKSPACE_DIR/tasks` | Task Queue .txt/.md source folder |
| `DB_PATH` | `$WORKSPACE_DIR/command_center.db` | SQLite database path |
| `QUICK_LAUNCH_JSON` | `$WORKSPACE_DIR/quick_launch.json` | Quick Launch button definitions |
| `LM_STUDIO_URL` | `http://localhost:1234` | LM Studio API base URL |
| `OPENCLAW_JSON` | `/home/mikegg/.openclaw/openclaw.json` | OpenClaw config (Telegram token source) |
| `MONTHLY_BUDGET` | `60.0` | Default monthly API budget USD |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `3000` | HTTP port |
| `LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG/INFO/WARNING/ERROR) |

---

## Data Sources — Every Panel Documented

### Panel 1 — System Health
- **Source:** `metrics.py` → `MetricsCollector.collect()` using **psutil**
- **Pushed:** WebSocket event `system_metrics` every **5 seconds** (task: `metrics_broadcaster` in `main.py`)
- **REST fallback:** `GET /api/system`
- **Data points:**
  - `cpu_percent` — `psutil.cpu_percent(interval=1)`
  - `memory_percent`, `memory_used`, `memory_total` — `psutil.virtual_memory()`
  - `swap_percent` — `psutil.swap_memory()`
  - `disks[]` — `psutil.disk_partitions()` + `disk_usage()` per mountpoint
  - `network.bytes_sent_per_sec`, `bytes_recv_per_sec` — `psutil.net_io_counters()` delta
- **To add a metric:** Edit `MetricsCollector.collect()` in `metrics.py` and `Metrics.to_dict()`, then add HTML element and update `renderSystemMetrics()` in `index.html`

---

### Panel 2 — Model Routing Monitor
- **Source:** SQLite table `routing_calls` in `command_center.db`
- **Populated by:** External agents calling `POST /api/routing`
- **Pushed:** WebSocket event `routing_call` on each new call; initial 50 entries sent in `init`
- **REST:** `GET /api/routing?limit=50` | `GET /api/routing/stats`
- **Data points:** `timestamp`, `provider`, `model_name`, `actual_model`, `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms`, `agent_name`
- **To log a call:**
  ```bash
  curl -X POST http://localhost:3000/api/routing \
    -H "Content-Type: application/json" \
    -d '{"provider":"anthropic","model_name":"claude-sonnet","agent_name":"my_agent",
         "tokens_in":1200,"tokens_out":400,"cost_usd":0.0048,"latency_ms":1800}'
  ```
- **To add columns:** Edit `database.py → add_routing_call()` and the `routing_calls` CREATE TABLE statement

---

### Panel 3 — Provider Status Nodes
- **Source:** Derived from `GET /api/providers` which aggregates the `routing_calls` table
- **Pushed:** Recomputed on every new routing call; also sent as `routing_stats` in the `init` payload
- **Data points per provider:** `calls_today`, `tokens_today`, `cost_today`, `last_call`, `active` (true if called within last 24h)
- **Providers tracked:** `anthropic`, `openai`, `openrouter`, `local`
- **To add a provider:** Add an entry to the `providers` list in `GET /api/providers` in `main.py`; add a `.pnode-*` CSS class and HTML node element in `index.html`

---

### Panel 4 — Budget Tracker
- **Source:** SQLite `budget` table + `routing_calls` aggregation via `database.py → get_budget_summary()`
- **Pushed:** WebSocket event `budget_update` on every new routing call; also hourly via `budget_reset_checker` task
- **REST:** `GET /api/budget` | `PUT /api/budget/config {"monthly_limit": 100.0}`
- **Data points:** `monthly_limit`, `total_spent`, `remaining`, `percent_used`, `daily_spent`, `daily_burn_rate`, `projected_month_end`, `by_provider` (dict keyed by provider name)
- **To adjust limit:** Command bar: `set budget 100` — or REST: `PUT /api/budget/config {"monthly_limit":100}`
- **Monthly reset:** Automatically resets on the 1st of each month. Reset date tracked in SQLite `budget` table (`reset_date` column).

---

### Panel 5 — Cron Job Monitor
- **Source:** SQLite `cron_jobs` table
- **Pushed:** WebSocket event `cron_update` on any change
- **REST:** `GET /api/crons` | `POST /api/crons` | `POST /api/crons/{name}/trigger`
- **Data points:** `name`, `schedule` (cron expression string), `description`, `command`, `last_run`, `next_run`, `run_count`, `last_status` (SUCCESS/RUNNING/FAILED/PENDING), `last_output`
- **Important:** The backend tracks metadata only. Real execution happens externally (system cron, systemd timers). Those should call `POST /api/crons/{name}/trigger` to mark runs.
- **To register a job:**
  ```bash
  curl -X POST http://localhost:3000/api/crons \
    -H "Content-Type: application/json" \
    -d '{"name":"daily_backup","schedule":"0 2 * * *","description":"Nightly backup"}'
  ```

---

### Panel 6 — Agent Registry
- **Source:** SQLite `agents` table
- **Pushed:** WebSocket event `agent_update` on any registration or status change
- **REST:** `GET /api/agents` | `POST /api/agents/register` | `POST /api/agents/{name}/status`
- **Data points:** `name`, `display_name`, `status` (idle/running/error), `last_action`, `last_active`, `metadata` (JSON blob)
- **Log drill-down:** Click any agent row in the UI → fetches `GET /api/agents/{name}/logs?limit=20`
- **Heartbeat auto-idle:** Agents with `status=running` that have not updated in >2 minutes are automatically set to `idle` by the `heartbeat_checker` background task in `main.py`
- **To register an agent:**
  ```bash
  curl -X POST http://localhost:3000/api/agents/register \
    -H "Content-Type: application/json" \
    -d '{"name":"my_agent","display_name":"My Agent","status":"idle","last_action":"Ready"}'
  ```

---

### Panel 7 — Live Log Feed
- **Source:** SQLite `logs` table; streamed live via WebSocket `new_log` event
- **REST:** `GET /api/logs?limit=200&level=ERROR&agent=my_agent` | `POST /api/logs` | `DELETE /api/logs`
- **Data points:** `id`, `timestamp`, `level` (INFO/WARN/ERROR/DEBUG/SUCCESS), `agent_name`, `message`
- **Client-side filters:** Level dropdown + agent name text input — no refetch needed
- **To write a log:**
  ```bash
  curl -X POST http://localhost:3000/api/logs \
    -H "Content-Type: application/json" \
    -d '{"message":"Task complete","level":"SUCCESS","agent_name":"my_agent"}'
  ```
- **Clear all logs:** Command bar: `clear logs` — or REST: `DELETE /api/logs`

---

### Panel 8 — LM Studio / Local GPU
- **Source:** `main.py → lmstudio_poller()` polling `GET {LM_STUDIO_URL}/v1/models` (OpenAI-compatible endpoint)
- **Pushed:** WebSocket event `lmstudio_update` every **15 seconds**
- **REST:** `GET /api/lmstudio`
- **WSL2 quirk:** LM Studio runs on the Windows host, not in WSL2. The poller tries `localhost:1234` first; if unreachable it automatically detects the WSL2 gateway IP via `ip route show default` and retries. No config change needed.
- **Data points:** `online` (bool), `model` (first loaded model ID), `url` (which address succeeded), `checked_at`
- **To change port:** Set `LM_STUDIO_URL=http://localhost:NNNN` in `.env` and restart

---

### Panel 9 — Telegram Bot
- **Source:** `main.py → telegram_poller()` calling `GET https://api.telegram.org/bot{TOKEN}/getMe`
- **Token location:** Read from `openclaw.json → channels.telegram.botToken`. The file is **never modified** — read-only access only.
- **Pushed:** WebSocket event `telegram_update` — immediately on startup, then every **30 seconds**
- **External webhook:** `POST /api/telegram/event` — call this from your bot handler to push live message counts
- **REST:** `GET /api/telegram` | `POST /api/telegram/event`
- **Data points:** `connected` (bool), `username`, `first_name`, `last_message` (ISO timestamp, from webhook), `messages_today` (from webhook), `checked_at`
- **To push message events from the bot:**
  ```json
  POST /api/telegram/event
  {"connected": true, "last_message": "2026-02-23T20:00:00", "messages_today": 12}
  ```
- **If token path changes:** Update `get_telegram_token()` in `main.py` to match the new JSON structure

---

### Panel 10 — Doc Drop Zone
- **Source:** Files stored to `UPLOADS_DIR`; metadata in SQLite `uploads` table
- **REST:** `POST /api/upload` (multipart/form-data) | `GET /api/uploads?limit=10`
- **Pushed:** WebSocket event `upload_complete` on each successful upload
- **Data points:** `filename` (sanitized), `original_name`, `size` (bytes), `timestamp`, `path`
- **Destination path:** `/home/mikegg/.openclaw/workspace/imports/uploaded-docs/`
- **Name collision:** If file exists, a timestamp suffix is added automatically
- **To change destination:** Set `UPLOADS_DIR` in `.env`

---

### Panel 11 — Quick Notes
- **Source:** SQLite `notes` table — single text blob stored under key `"notes"`
- **REST:** `GET /api/notes` | `POST /api/notes {"content":"your text"}`
- **Auto-save:** Debounced — saves 1 second after you stop typing
- **Persists across restarts:** Loaded from SQLite in the `init` WebSocket payload

---

### Panel 12 — Task Queue
- **Source:** Filesystem — all `.txt` and `.md` files in `TASKS_DIR`
- **TASKS_DIR:** `/home/mikegg/.openclaw/workspace/tasks/`
- **Live updates:** **watchdog** filesystem watcher fires on file create/modify/delete (0.5s debounce). Falls back to polling every **60 seconds** if watchdog is unavailable.
- **REST:** `GET /api/tasks` | `GET /api/tasks/open-folder`
- **Pushed:** WebSocket event `tasks_update`
- **Data points per file:** `filename`, `title` (stem, dash/underscore prettified), `content` (full raw text), `done` (bool), `modified` (Unix timestamp), `modified_str`
- **Done convention:** Prefix filename with `done-` or `done_` → renders struck-through in UI
  - Example: rename `today.md` to `done-today.md` to mark complete
- **To add tasks:** Drop `.md` or `.txt` files into `tasks/` folder — appear instantly via watchdog
- **watchdog install check:** `venv/bin/pip show watchdog`

---

### Panel 13 — Avatar / Mood Display
- **Source:** `avatar.py → AvatarManager` + `main.py → avatar_updater()` background task (every 10s)
- **Pushed:** WebSocket event `avatar_update` every **10 seconds**; also after `POST /api/avatar/cycle`
- **Auto-cycle:** Frontend calls `POST /api/avatar/cycle` every **30 seconds** to rotate images
- **REST:** `GET /api/avatar` | `POST /api/avatar/cycle` | `POST /api/avatar/reload`
- **Image location:** `AVATARS_DIR` = `/home/mikegg/.openclaw/workspace/avatars/`
- **Mood matching — filename prefix convention:**

  | Filename prefix | Mood shown | Triggered when |
  |---|---|---|
  | `idle-*` | IDLE | Default / no other condition met |
  | `happy-*` | HAPPY | Low CPU/RAM, no errors, recent activity |
  | `thinking-*` | THINKING | Any agent has `status=running` |
  | `alert-*` | ALERT | CPU > 80% OR RAM > 80% OR budget > 90% |
  | `error-*` | ERROR | Any log with `level=ERROR` in last 10 entries |
  | `bored-*` | BORED | No activity for > 30 minutes |

- **Mood logic file:** `avatar.py → AvatarManager.update()` — edit thresholds here
- **To add images:** Drop PNG/JPG files with mood prefix into `avatars/` then `POST /api/avatar/reload`
- **To change mood thresholds:** Edit `AvatarManager.update()` in `avatar.py`

---

## Quick Launch Buttons

Defined in `/home/mikegg/.openclaw/workspace/quick_launch.json`. Hot-reloaded every 5 seconds.

```json
[
  {"label": "Health Check",   "command": "trigger health_check",          "color": "#00ff88"},
  {"label": "Clear Logs",     "command": "clear logs",                    "color": "#6080a0"},
  {"label": "Reload Avatars", "command": "reload avatars",                "color": "#00f0ff"},
  {"label": "Daily Summary",  "command": "trigger daily_summary",         "color": "#ffaa00"},
  {"label": "Agent Status",   "command": "run claude_agent status check", "color": "#ff00c8"},
  {"label": "Budget Report",  "command": "trigger budget_report",         "color": "#aa88ff"}
]
```

Edit and save — buttons update without a restart.

---

## Command Bar

Type commands at the bottom of the screen. Tab-completion works for job/agent names.

| Command | Effect |
|---|---|
| `trigger <job_name>` | Manually trigger a registered cron job |
| `restart <agent_name>` | Reset agent status to idle |
| `run <agent_name> <prompt>` | Mark agent as running with a prompt label |
| `clear logs` | Clear all logs from the database |
| `reload avatars` | Rescan the avatars directory |
| `set budget <amount>` | Set monthly budget limit in USD |

---

## Full API Reference

All endpoints on `http://localhost:3000`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/system` | CPU, RAM, disk, network metrics |
| GET | `/api/agents` | All registered agents |
| POST | `/api/agents/register` | Register or update an agent |
| POST | `/api/agents/{name}/status` | Update agent status |
| GET | `/api/agents/{name}/logs` | Agent-specific logs |
| GET | `/api/logs` | Fetch logs (`?level=` `?agent=` `?limit=`) |
| POST | `/api/logs` | Write a log entry |
| DELETE | `/api/logs` | Clear all logs |
| GET | `/api/routing` | Recent routing calls (`?limit=`) |
| POST | `/api/routing` | Record a routing call |
| GET | `/api/routing/stats` | Per-provider aggregated stats |
| GET | `/api/budget` | Budget summary |
| PUT | `/api/budget/config` | Set monthly/daily limits |
| GET | `/api/crons` | All cron jobs |
| POST | `/api/crons` | Register a cron job |
| POST | `/api/crons/{name}/trigger` | Trigger a cron job manually |
| GET | `/api/avatar` | Current avatar state |
| POST | `/api/avatar/cycle` | Advance to next avatar image |
| POST | `/api/avatar/reload` | Rescan avatars directory |
| GET | `/api/providers` | Provider status + today's stats |
| GET | `/api/lmstudio` | LM Studio connection status |
| GET | `/api/telegram` | Telegram bot status |
| POST | `/api/telegram/event` | Push Telegram message event (from webhook) |
| POST | `/api/upload` | Upload a file (multipart/form-data) |
| GET | `/api/uploads` | Recent upload history |
| GET | `/api/notes` | Retrieve quick notes |
| POST | `/api/notes` | Save quick notes |
| GET | `/api/quicklaunch` | Quick Launch button config |
| GET | `/api/tasks` | Task files from tasks/ folder |
| GET | `/api/tasks/open-folder` | Open tasks folder in file manager |
| POST | `/api/command` | Execute a text command |
| WS | `/ws` | WebSocket real-time event feed |

---

## WebSocket Event Reference

Connect to `ws://localhost:3000/ws`. First message is always a full `init` snapshot.

**Server → Client:**

| Event | Payload | Trigger |
|---|---|---|
| `init` | Full state snapshot | On WebSocket connect |
| `system_metrics` | CPU/RAM/disk/network dict | Every 5s |
| `new_log` | Single log entry | POST /api/logs |
| `logs_cleared` | `{}` | DELETE /api/logs |
| `routing_call` | Single routing call | POST /api/routing |
| `agent_update` | Full agents array | Any agent change |
| `budget_update` | Budget summary | New routing call or hourly |
| `cron_update` | Full cron jobs array | Any cron change |
| `avatar_update` | Avatar state | Every 10s |
| `lmstudio_update` | LM Studio status | Every 15s |
| `telegram_update` | Telegram status | Startup + every 30s |
| `upload_complete` | Upload record | Successful file upload |
| `quicklaunch_update` | Buttons array | Every 5s |
| `activity_tick` | Last activity record | Every 5s |
| `tasks_update` | Task files array | File change in tasks/ or every 60s |

**Client → Server:**

| Message | Response |
|---|---|
| `{"type":"ping"}` | `{"type":"pong","ts":"..."}` |

---

## Tile Layout

All tiles including the Avatar are drag-and-drop (GridStack.js, 12-column grid, 55px cell height).

- **Move:** Drag the **panel header**
- **Resize:** Drag **bottom-right or bottom-left corner**
- **Auto-save:** Layout saved to `localStorage` key `cc-layout`
- **Reset:** Click **⊞ RESET LAYOUT** button (top-right header)

**Default positions:**

| Panel | x | y | w | h |
|---|---|---|---|---|
| Avatar | 0 | 0 | 3 | 14 |
| System Health | 3 | 0 | 3 | 5 |
| Model Routing | 6 | 0 | 6 | 5 |
| Provider Nodes | 3 | 5 | 3 | 6 |
| Budget Tracker | 6 | 5 | 3 | 6 |
| Cron Jobs | 9 | 5 | 3 | 6 |
| Agent Registry | 3 | 11 | 6 | 5 |
| Live Logs | 9 | 11 | 3 | 5 |
| LM Studio | 3 | 16 | 3 | 4 |
| Telegram | 6 | 16 | 3 | 4 |
| Doc Drop Zone | 9 | 16 | 3 | 4 |
| Quick Notes | 0 | 20 | 12 | 5 |

---

## systemd Service

```bash
systemctl --user enable arden-command-center   # Auto-start on WSL boot
systemctl --user start arden-command-center
systemctl --user stop arden-command-center
systemctl --user restart arden-command-center
journalctl --user -u arden-command-center -f   # Live log tail
journalctl --user -u arden-command-center -n 50
```

**WSL2:** Auto-start requires `systemd=true` in `/etc/wsl.conf`. Without it, run `systemctl --user start arden-command-center` manually after each WSL restart.

---

## Troubleshooting

### Port 3000 unreachable
```bash
systemctl --user status arden-command-center
ss -tlnp | grep 3000
```

### Avatar blank
```bash
ls /home/mikegg/.openclaw/workspace/avatars/          # Must have mood-prefixed files
curl -I http://localhost:3000/avatars/idle-ref01.png  # Test static serving
curl -X POST http://localhost:3000/api/avatar/reload  # Force rescan
```

### Telegram OFFLINE
```bash
python3 -c "import json; d=json.load(open('/home/mikegg/.openclaw/openclaw.json')); print(d['channels']['telegram']['botToken'])"
curl "https://api.telegram.org/bot<TOKEN>/getMe"
# If token path changed: update get_telegram_token() in main.py
```

### LM Studio OFFLINE
```bash
ip route show default | awk '/via/ {print $3}'      # Get Windows host IP
curl http://<GATEWAY_IP>:1234/v1/models              # Test from WSL2
# Non-default port: set LM_STUDIO_URL=http://localhost:NNNN in .env
```

### Tasks not live-updating
```bash
venv/bin/pip install watchdog
journalctl --user -u arden-command-center | grep -i watchdog
# Should show: "Watchdog watching tasks dir: ..."
# Without watchdog: 60s polling fallback
```

### GridStack tiles wrong position
- Click **⊞ RESET LAYOUT** in header, OR
- DevTools → Application → Local Storage → delete `cc-layout`

### Database problems
```bash
sqlite3 /home/mikegg/.openclaw/workspace/command_center.db ".tables"
# Expected: agents  budget  cron_jobs  logs  notes  routing_calls  uploads
cp /home/mikegg/.openclaw/workspace/command_center.db ~/cc_backup_$(date +%Y%m%d).db
sqlite3 /home/mikegg/.openclaw/workspace/command_center.db "DELETE FROM logs;"
```

### Service won't start
```bash
journalctl --user -u arden-command-center -n 30
venv/bin/pip install -r requirements.txt
cp arden-command-center.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user restart arden-command-center
```

---

## Adding a New Panel

1. **`main.py`** — Add `GET /api/mypanel` route, add a poller calling `await manager.broadcast("mypanel_update", data)`, add `"mypanel": get_my_data()` to the `init` WebSocket payload
2. **`database.py`** — Add helper + SQLite table if persistence is needed
3. **`index.html`** — Add CSS, add GridStack item HTML, add `case 'mypanel_update':` in `handleEvent()`, add `renderMyPanel()` function, add entry to `DEFAULT_LAYOUT`
4. **Restart** — `systemctl --user restart arden-command-center`

---

*Arden // Command Center — OpenClaw — mikegg@Goody-2025 — WSL2 Ubuntu 24.04*
