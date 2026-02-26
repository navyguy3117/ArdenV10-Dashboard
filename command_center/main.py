"""
main.py - FastAPI backend for Arden // Command Center
Fixes: LM Studio URL, Telegram Bot API, watchdog tasks folder
New: /api/tasks endpoint, tasks folder watchdog, telegram Bot API polling
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiofiles
import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import (
    Depends, FastAPI, File, HTTPException, Request,
    UploadFile, WebSocket, WebSocketDisconnect
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

load_dotenv(Path(__file__).parent / ".env")

from avatar import AvatarManager
from database import Database
from metrics import MetricsCollector

# ── Configuration ──────────────────────────────────────────────────────────────
WORKSPACE       = Path(os.getenv("WORKSPACE_DIR", "/home/mikegg/.openclaw/workspace"))
AVATARS_DIR     = Path(os.getenv("AVATARS_DIR",   str(WORKSPACE / "avatars")))
UPLOADS_DIR     = Path(os.getenv("UPLOADS_DIR",   str(WORKSPACE / "imports/uploaded-docs")))
TASKS_DIR       = Path(os.getenv("TASKS_DIR",     str(WORKSPACE / "tasks")))
DB_PATH         = os.getenv("DB_PATH",            str(WORKSPACE / "command_center.db"))
QUICK_LAUNCH_JSON = Path(os.getenv("QUICK_LAUNCH_JSON", str(WORKSPACE / "quick_launch.json")))
LM_STUDIO_URL   = os.getenv("LM_STUDIO_URL",  "http://localhost:1234")
CORTEX_URL      = os.getenv("CORTEX_URL",     "http://10.10.10.180:3100")
ARDEN_KNOWLEDGE = WORKSPACE / "arden" / "knowledge"
# Full path to powershell.exe for WSL2→Windows host metrics
POWERSHELL      = "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe"

# ── Per-model cost rates (USD per 1M tokens: input, output) ──────────────────
_MODEL_COSTS = {
    "anthropic": {
        # ── Claude 4 series (current) ────────────────────────────────────────
        "claude-sonnet-4-5":           (3.0,  15.0),
        "claude-sonnet-4-6":           (3.0,  15.0),
        "claude-haiku-4-5":            (0.80,  4.0),
        "claude-haiku-4-5-20251001":   (0.80,  4.0),
        # ── Claude 3.x series ───────────────────────────────────────────────
        "claude-3-7-sonnet-20250219":  (3.0,  15.0),
        "claude-3-5-sonnet-20241022":  (3.0,  15.0),
        "claude-3-5-haiku-20241022":   (0.80,  4.0),
        "claude-3-opus-20240229":      (15.0, 75.0),
    },
    "openai": {
        "gpt-4o-mini":                 (0.15,  0.60),
        "gpt-4o":                      (2.50, 10.0),
        "gpt-4.1":                     (2.00,  8.0),
        "gpt-4.1-mini":                (0.40,  1.60),
        "o3-mini":                     (1.10,  4.40),
        "o1-mini":                     (1.10,  4.40),
        "o1":                          (15.0, 60.0),
    },
    "google": {
        # ── Gemini 2.5 series (current) ─────────────────────────────────────
        "gemini-2.5-flash":            (0.15,  0.60),
        "gemini-2.5-flash-lite":       (0.075, 0.30),
        "gemini-2.5-pro":              (1.25, 10.0),
        "gemini-flash-latest":         (0.15,  0.60),   # stable alias
        # ── Gemini 1.5 (stable) ─────────────────────────────────────────────
        "gemini-1.5-pro":              (1.25,  5.0),
        "gemini-1.5-flash":            (0.075, 0.30),
        "gemini-1.5-flash-8b":         (0.0375,0.15),
    },
}

def _calc_cost(provider: str, model: str, tokens_in: int, tokens_out: int,
               actual_cost: float = None) -> float:
    """Return cost in USD. Uses actual_cost if provided (e.g. from OpenRouter response)."""
    if actual_cost is not None:
        return round(float(actual_cost), 8)
    rates = _MODEL_COSTS.get(provider, {})
    in_rate, out_rate = rates.get(model, (1.0, 3.0))   # fallback: $1/$3 per 1M
    return round((tokens_in * in_rate + tokens_out * out_rate) / 1_000_000, 8)

OPENCLAW_JSON   = Path(os.getenv("OPENCLAW_JSON", "/home/mikegg/.openclaw/openclaw.json"))
MONTHLY_BUDGET  = float(os.getenv("MONTHLY_BUDGET", "60.0"))
HOST            = os.getenv("HOST", "0.0.0.0")
PORT            = int(os.getenv("PORT", "3000"))
LOG_LEVEL       = os.getenv("LOG_LEVEL", "INFO")

# Ensure directories exist
OBSERVER_DIR    = WORKSPACE / "imports" / "observer"

for d in [AVATARS_DIR, UPLOADS_DIR, TASKS_DIR, OBSERVER_DIR, ARDEN_KNOWLEDGE]:
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("command_center")

# ── Authentication ────────────────────────────────────────────────────────────
# Set CC_PASSWORD in .env (or env var) to enable the login wall.
# If unset, auth is DISABLED (open access — local-dev mode).
CC_PASSWORD     = os.getenv("CC_PASSWORD", "")          # plaintext or bcrypt hash
CC_SECRET       = os.getenv("CC_SECRET", secrets.token_hex(32))  # JWT signing key
CC_TOKEN_HOURS  = int(os.getenv("CC_TOKEN_HOURS", "24"))         # token TTL

AUTH_ENABLED    = bool(CC_PASSWORD)

import base64, struct

def _jwt_encode(payload: dict) -> str:
    """Minimal HS256 JWT — no external dependency."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=")
    body   = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
    sig_input = header + b"." + body
    sig = base64.urlsafe_b64encode(
        hmac.new(CC_SECRET.encode(), sig_input, hashlib.sha256).digest()
    ).rstrip(b"=")
    return (sig_input + b"." + sig).decode()

def _jwt_decode(token: str) -> Optional[dict]:
    """Verify HS256 JWT, return payload or None."""
    try:
        parts = token.encode().split(b".")
        if len(parts) != 3:
            return None
        sig_input = parts[0] + b"." + parts[1]
        expected  = base64.urlsafe_b64encode(
            hmac.new(CC_SECRET.encode(), sig_input, hashlib.sha256).digest()
        ).rstrip(b"=")
        if not hmac.compare_digest(expected, parts[2]):
            return None
        # Pad base64
        body = parts[1] + b"=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None

def _check_password(provided: str) -> bool:
    """Compare password — supports plaintext or simple SHA-256 hash."""
    if CC_PASSWORD.startswith("sha256:"):
        expected = CC_PASSWORD[7:]
        return hmac.compare_digest(
            hashlib.sha256(provided.encode()).hexdigest(), expected
        )
    return hmac.compare_digest(provided, CC_PASSWORD)

# Paths that skip auth (login page, static assets, health)
_PUBLIC_PREFIXES = ("/api/auth/", "/static/", "/avatars/", "/favicon")
_PUBLIC_EXACT    = {"/", "/health"}

# ── Singletons ─────────────────────────────────────────────────────────────────
db               = Database(DB_PATH)
metrics_collector = MetricsCollector()
avatar_manager   = AvatarManager(str(AVATARS_DIR))

# Remote (on-network) LM Studio — 4090 in Ubuntu container on Proxmox
LM_STUDIO_NET_URL     = os.getenv("LM_STUDIO_NET_URL",     "http://10.10.10.180:1234")
# GPU stats agent on the Proxmox node (gpu_stats_server.py on port 18765)
LM_STUDIO_NET_GPU_URL = os.getenv("LM_STUDIO_NET_GPU_URL", "http://10.10.10.180:18765")

# Mutable state
_lm_studio_status: Dict  = {
    "online": False, "model": None, "loaded_models": [], "all_models": [],
    "not_loaded_models": [], "vram_used": None, "checked_at": None, "url": None,
    "gpu": None, "stats": {"tokens_per_second": None, "ttft_ms": None}
}
_lm_studio_net_status: Dict = {
    "online": False, "model": None, "loaded_models": [], "all_models": [],
    "not_loaded_models": [], "vram_used": None, "checked_at": None,
    "url": LM_STUDIO_NET_URL, "label": "LM NETWORK // 4090", "gpu": None,
}
_telegram_status: Dict   = {"connected": False, "last_message": None, "messages_today": 0,
                              "checked_at": None, "username": None}
_quick_launch_buttons: List[Dict] = []
_quick_launch_mtime: float = 0.0
_last_metrics: Dict = {}
_gpu_metrics: Optional[Dict] = None
_processing_agents: Set[str] = set()
_local_pc_metrics: Dict = {"available": False, "cpu_name": "AMD Ryzen 9 9800X3D", "ram_label": "128GB DDR5"}

# ── Routing telemetry in-memory ring buffer (last 200 instrumented calls) ──────
_routing_calls_log: List[Dict] = []
_routing_calls_max = 200

# ── SSE clients for telemetry stream ───────────────────────────────────────────
_sse_clients: List = []  # asyncio.Queue instances

# ── Cortex memory: conversation buffer for periodic ingest ────────────────────
_cortex_conv_buffer: List[Dict] = []
_cortex_last_ingest: str = datetime.utcnow().isoformat()
_cortex_last_digest: str = ""  # ISO timestamp of last nightly digest

# ── Helpers ────────────────────────────────────────────────────────────────────
def get_telegram_token() -> Optional[str]:
    """Read Telegram bot token from openclaw.json."""
    try:
        if OPENCLAW_JSON.exists():
            cfg = json.loads(OPENCLAW_JSON.read_text(encoding="utf-8"))
            token = (cfg.get("channels", {}).get("telegram", {}).get("botToken")
                     or cfg.get("telegram", {}).get("bot_token")
                     or cfg.get("telegram", {}).get("botToken"))
            return token
    except Exception as e:
        logger.error(f"Failed to read telegram token: {e}")
    return None


def get_wsl_gateway() -> Optional[str]:
    """Try to find WSL2 gateway IP to reach Windows-hosted services."""
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=2
        )
        parts = result.stdout.strip().split()
        if "via" in parts:
            return parts[parts.index("via") + 1]
    except Exception:
        pass
    return None


def get_gpu_metrics() -> Dict:
    """Get NVIDIA GPU metrics via nvidia-smi. Returns available=False if no GPU."""
    # Try paths in priority order — WSL2 driver path first
    SMI_PATHS = ["/usr/lib/wsl/lib/nvidia-smi", "nvidia-smi", "/usr/bin/nvidia-smi"]
    result = None
    for smi_cmd in SMI_PATHS:
        try:
            result = subprocess.run(
                [smi_cmd,
                 "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=4
            )
            if result.returncode == 0:
                break
        except FileNotFoundError:
            continue
    try:
        if result is not None and result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) >= 5:
                mem_used = float(parts[3])
                mem_total = float(parts[4])
                power_w = None
                if len(parts) >= 6 and parts[5] not in ("[N/A]", "N/A", ""):
                    try:
                        power_w = float(parts[5])
                    except ValueError:
                        pass
                return {
                    "available": True,
                    "name": parts[0],
                    "temp_c": float(parts[1]),
                    "util_pct": float(parts[2]),
                    "mem_used_mb": mem_used,
                    "mem_total_mb": mem_total,
                    "mem_pct": round(mem_used / mem_total * 100, 1) if mem_total > 0 else 0,
                    "power_w": power_w,
                }
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"GPU metrics: {e}")
    return {"available": False}


def get_local_pc_metrics() -> Dict:
    """Query Windows host CPU + RAM + temp via powershell.exe from WSL2."""
    try:
        ps_cmd = (
            # CimInstance Win32_Processor is faster/more reliable than Get-Counter
            "$cpu=(Get-CimInstance Win32_Processor"
            " | Measure-Object -Property LoadPercentage -Average).Average;"
            # RAM from OS
            "$m=(Get-CimInstance Win32_OperatingSystem);"
            # CPU temp via ACPI thermal zones (graceful fallback to $null)
            "$temp=$null;"
            "try{"
            "  $tz=(Get-CimInstance -Namespace 'root/WMI'"
            "       -ClassName MSAcpi_ThermalZoneTemperature"
            "       -ErrorAction SilentlyContinue);"
            "  if($tz){"
            "    $raw=($tz|Measure-Object -Property CurrentTemperature -Maximum).Maximum;"
            "    $c=[math]::Round($raw/10.0-273.15,1);"
            "    if($c -gt 0 -and $c -lt 120){$temp=$c}"
            "  }"
            "}catch{}"
            "Write-Output (ConvertTo-Json @{"
            "  ram_total_gb=[math]::Round($m.TotalVisibleMemorySize/1MB,1);"
            "  ram_free_gb=[math]::Round($m.FreePhysicalMemory/1MB,1);"
            "  cpu_pct=[math]::Round([double]$cpu,1);"
            "  cpu_temp_c=$temp})"
        )
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            ram_total = float(data.get("ram_total_gb", 128.0))
            ram_free  = float(data.get("ram_free_gb", 0.0))
            ram_used_pct = round((1 - ram_free / max(ram_total, 0.001)) * 100, 1)
            cpu_pct   = float(data.get("cpu_pct", 0))
            cpu_temp  = data.get("cpu_temp_c")  # None if unavailable
            return {
                "available":    True,
                "cpu_pct":      cpu_pct,
                "cpu_temp_c":   cpu_temp,
                "ram_used_pct": ram_used_pct,
                "ram_used_gb":  round(ram_total - ram_free, 1),
                "ram_total_gb": ram_total,
                "cpu_name":     "AMD Ryzen 9 9800X3D",
                "ram_label":    "128GB DDR5",
                "updated_at":   datetime.utcnow().isoformat(),
            }
    except Exception as e:
        logger.debug(f"Local PC metrics error: {e}")
    return {
        "available": False,
        "cpu_name":  "AMD Ryzen 9 9800X3D",
        "ram_label": "128GB DDR5",
        "updated_at": datetime.utcnow().isoformat(),
    }


def get_provider_registry() -> Dict:
    """
    Build provider registry from env vars.
    Checks PROVIDER_API_KEY_BUCKET_1..4 and main keys.
    Returns sanitized dict — never exposes actual key values.
    """
    providers = {}
    key_map = {
        "openai":     "OPENAI_API_KEY",
        "anthropic":  "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "google":     "GOOGLE_API_KEY",
    }
    for provider, env_prefix in key_map.items():
        buckets = {}
        for i in range(1, 5):
            env_var = f"{env_prefix}_BUCKET_{i}"
            val = os.getenv(env_var, "")
            if not val:
                try:
                    res = subprocess.run(
                        ["bash", "-l", "-c", f"echo ${{{env_var}}}"],
                        capture_output=True, text=True, timeout=3
                    )
                    v = res.stdout.strip()
                    if v and not v.startswith("$"):
                        val = v
                except Exception:
                    pass
            buckets[f"bucket_{i}"] = "present" if val else "missing"
        main_key = get_api_key(provider)
        providers[provider] = {
            "main_key": "present" if main_key else "missing",
            "buckets": buckets,
            "model": {
                "anthropic": "claude-sonnet-4-20250514",
                "openai": "gpt-4o",
                "openrouter": "openai/gpt-4o",
                "google": "gemini-2.5-flash",
            }.get(provider, "unknown"),
        }
    return providers


def compute_global_severity(cpu_pct: float = 0, ram_pct: float = 0,
                             budget_pct: float = 0) -> str:
    """Return ok/warn/hot/crit based on worst observed metric."""
    worst = max(cpu_pct, ram_pct, budget_pct)
    if worst >= 90:
        return "crit"
    if worst >= 75:
        return "hot"
    if worst >= 50:
        return "warn"
    return "ok"


def get_api_key(provider: str) -> Optional[str]:
    """Read API key for a given provider from env or openclaw.json or ~/.bashrc."""
    env_map = {
        "anthropic":  "ANTHROPIC_API_KEY",
        "openai":     "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "google":     "GOOGLE_API_KEY",
    }
    env_var = env_map.get(provider)

    # 1) Process environment
    if env_var and os.getenv(env_var):
        return os.getenv(env_var)

    # 2) Ask a login shell — most reliable way for systemd user services
    if env_var:
        try:
            result = subprocess.run(
                ["bash", "-l", "-c", f"echo ${{{env_var}}}"],
                capture_output=True, text=True, timeout=5,
                env={**os.environ, "HOME": str(Path.home())}
            )
            val = result.stdout.strip()
            # Make sure it was actually expanded (not the literal "${VAR}")
            if val and not val.startswith("$"):
                return val
        except Exception:
            pass

        # 2b) Parse export lines from shell startup files as extra fallback
        for rc_path in [Path.home() / ".bashrc", Path.home() / ".profile", Path.home() / ".bash_profile"]:
            try:
                if rc_path.exists():
                    for line in rc_path.read_text(encoding="utf-8").splitlines():
                        stripped = line.strip()
                        if stripped.startswith(f"export {env_var}="):
                            val = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                            if val and not val.startswith("$"):
                                return val
            except Exception:
                pass

    # 3) openclaw.json various paths
    try:
        if OPENCLAW_JSON.exists():
            cfg = json.loads(OPENCLAW_JSON.read_text(encoding="utf-8"))
            key = (cfg.get(provider, {}).get("apiKey")
                   or cfg.get(provider, {}).get("api_key")
                   or cfg.get("apiKeys", {}).get(provider)
                   or cfg.get("keys", {}).get(provider))
            return key
    except Exception:
        pass
    return None


def get_tasks() -> List[Dict]:
    """Read all .txt and .md files from TASKS_DIR."""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    try:
        for f in sorted(TASKS_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in (".txt", ".md"):
                try:
                    stem = f.stem
                    done = stem.lower().startswith("done-") or stem.lower().startswith("done_")
                    display_title = stem
                    if done:
                        display_title = stem[5:] if stem.lower().startswith("done-") else stem[5:]
                    display_title = display_title.replace("-", " ").replace("_", " ").strip().title()
                    content = f.read_text(encoding="utf-8", errors="replace")
                    tasks.append({
                        "filename": f.name,
                        "title": display_title,
                        "content": content,
                        "done": done,
                        "modified": f.stat().st_mtime,
                        "modified_str": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
                except Exception as e:
                    logger.warning(f"Could not read task file {f.name}: {e}")
    except Exception as e:
        logger.error(f"get_tasks error: {e}")
    return tasks


# ── WebSocket Manager ──────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info(f"WS client connected ({len(self.active)} total)")

    def disconnect(self, ws: WebSocket):
        try:
            self.active.remove(ws)
        except ValueError:
            pass
        logger.info(f"WS client disconnected ({len(self.active)} remaining)")

    async def broadcast(self, event_type: str, data: Any):
        if not self.active:
            return
        msg = json.dumps({
            "type": event_type,
            "data": data,
            "ts": datetime.utcnow().isoformat(),
        })
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


def _add_routing_log(call: Dict):
    """Append a routing call to in-memory ring buffer and notify SSE clients."""
    global _routing_calls_log
    _routing_calls_log.append(call)
    if len(_routing_calls_log) > _routing_calls_max:
        _routing_calls_log = _routing_calls_log[-_routing_calls_max:]
    # Notify SSE clients
    msg = json.dumps({"type": "routing_call", "data": call, "ts": datetime.utcnow().isoformat()})
    dead = []
    for q in _sse_clients:
        try:
            q.put_nowait(msg)
        except Exception:
            dead.append(q)
    for q in dead:
        try:
            _sse_clients.remove(q)
        except ValueError:
            pass


# ── Watchdog: tasks folder ─────────────────────────────────────────────────────
if WATCHDOG_AVAILABLE:
    class TaskFolderHandler(FileSystemEventHandler):
        def __init__(self, loop: asyncio.AbstractEventLoop):
            self._loop = loop
            self._timer: Optional[threading.Timer] = None

        def _schedule_broadcast(self):
            if self._timer and self._timer.is_alive():
                self._timer.cancel()
            self._timer = threading.Timer(0.5, self._do_broadcast)
            self._timer.daemon = True
            self._timer.start()

        def _do_broadcast(self):
            tasks = get_tasks()
            asyncio.run_coroutine_threadsafe(
                manager.broadcast("tasks_update", tasks),
                self._loop
            )

        def on_any_event(self, event):
            if not event.is_directory:
                path = getattr(event, "src_path", "")
                if path.endswith((".txt", ".md")):
                    self._schedule_broadcast()


# ── Quick Launch ───────────────────────────────────────────────────────────────
def load_quick_launch() -> List[Dict]:
    global _quick_launch_buttons, _quick_launch_mtime
    if not QUICK_LAUNCH_JSON.exists():
        default = [
            {"label": "Health Check",  "command": "trigger health_check",          "color": "#00ff88"},
            {"label": "Clear Logs",    "command": "clear logs",                     "color": "#6080a0"},
            {"label": "Reload Avatars","command": "reload avatars",                 "color": "#00f0ff"},
            {"label": "Daily Summary", "command": "trigger daily_summary",          "color": "#ffaa00"},
            {"label": "Agent Status",  "command": "run claude_agent status check",  "color": "#ff00c8"},
            {"label": "Budget Report", "command": "trigger budget_report",          "color": "#aa88ff"},
        ]
        QUICK_LAUNCH_JSON.write_text(json.dumps(default, indent=2))
        _quick_launch_buttons = default
        _quick_launch_mtime = QUICK_LAUNCH_JSON.stat().st_mtime
        return default
    try:
        mtime = QUICK_LAUNCH_JSON.stat().st_mtime
        if mtime != _quick_launch_mtime:
            _quick_launch_buttons = json.loads(QUICK_LAUNCH_JSON.read_text())
            _quick_launch_mtime = mtime
    except Exception as e:
        logger.error(f"Quick launch load error: {e}")
    return _quick_launch_buttons


# ── Background Tasks ───────────────────────────────────────────────────────────
async def metrics_broadcaster():
    global _last_metrics, _gpu_metrics
    # Brief warm-up so psutil has a reference interval before first collect
    await asyncio.sleep(1)
    while True:
        try:
            metrics = metrics_collector.collect()
            _last_metrics = metrics.to_dict()
            _gpu_metrics = get_gpu_metrics()
            payload = {**_last_metrics, "gpu": _gpu_metrics}
            await manager.broadcast("system_metrics", payload)
            # Also push severity update to SSE clients
            cpu = _last_metrics.get("cpu_percent", 0) or 0
            ram = _last_metrics.get("memory_percent", 0) or 0
            budget = db.get_budget_summary()
            sev_msg = json.dumps({
                "type": "system_metrics",
                "data": payload,
                "severity": compute_global_severity(cpu, ram, budget.get("percent_used", 0) or 0),
                "ts": datetime.utcnow().isoformat(),
            })
            for q in list(_sse_clients):
                try:
                    q.put_nowait(sev_msg)
                except Exception:
                    pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Metrics broadcaster: {e}")
        await asyncio.sleep(5)


async def avatar_updater():
    while True:
        try:
            await asyncio.sleep(10)
            processing = len(_processing_agents) > 0
            minutes_idle = 999.0  # default: unknown/inactive

            # Activity from log table (manual commands, etc.)
            last_act = db.get_last_activity()
            if last_act:
                try:
                    last_ts = datetime.fromisoformat(last_act["timestamp"])
                    log_idle = (datetime.utcnow() - last_ts).total_seconds() / 60
                    minutes_idle = min(minutes_idle, log_idle)
                except Exception:
                    pass

            # Activity from routing calls (Claw / router traffic)
            # Router writes directly to routing_calls table — check it here
            last_call_ts = None
            last_provider = None
            recent_calls = db.get_routing_calls(limit=1)
            if recent_calls:
                try:
                    rc = recent_calls[0]
                    call_ts = datetime.fromisoformat(rc["timestamp"].rstrip("Z"))
                    routing_idle = (datetime.utcnow() - call_ts).total_seconds() / 60
                    minutes_idle = min(minutes_idle, routing_idle)
                    last_call_ts = rc["timestamp"]
                    last_provider = rc.get("provider", "")
                    # If called within last 30 seconds → currently processing
                    if routing_idle < 0.5:
                        processing = True
                except Exception:
                    pass

            recent_logs = db.get_logs(limit=10)
            has_errors = any(l["level"] == "ERROR" for l in recent_logs)
            budget = db.get_budget_summary()
            state = avatar_manager.update(
                cpu_percent=(_last_metrics or {}).get("cpu_percent", 0),
                memory_percent=(_last_metrics or {}).get("memory_percent", 0),
                has_errors=has_errors,
                budget_percent=budget.get("percent_used", 0),
                minutes_since_activity=minutes_idle,
                processing=processing,
            )
            # Augment state with routing context for LAST ACT display
            if last_call_ts:
                state["last_call_ts"] = last_call_ts
                state["last_provider"] = last_provider
            await manager.broadcast("avatar_update", state)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Avatar updater: {e}")


def _build_lmstudio_urls() -> List[str]:
    """Build list of LM Studio base URLs to try (direct IP preferred, then gateway)."""
    base = LM_STUDIO_URL.rstrip("/")
    # If localhost, also try direct IP from TOOLS.md and WSL gateway
    if "localhost" in base or "127.0.0.1" in base:
        gateway = get_wsl_gateway()
        candidates = [base]
        candidates.append("http://10.10.10.98:1234")  # Gaming rig direct IP
        if gateway:
            candidates.append(base.replace("localhost", gateway).replace("127.0.0.1", gateway))
        return candidates
    return [base]


async def lmstudio_poller():
    """
    Poll LM Studio at /api/v0/models (correct LM Studio REST API v0).
    Tries direct IP (10.10.10.98:1234) and WSL2 gateway as fallbacks.
    Stores: loaded models, all downloaded models, stats.
    NOTE: LM Studio unload uses POST /api/v1/models/unload NOT DELETE /v1/models/<id>
    """
    global _lm_studio_status
    while True:
        try:
            await asyncio.sleep(12)
            bases = _build_lmstudio_urls()
            found = False
            for base in bases:
                try:
                    # Use /api/v0/models which returns state info (loaded/not-loaded)
                    url = f"{base}/api/v0/models"
                    timeout = aiohttp.ClientTimeout(total=4)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                data = await resp.json(content_type=None)
                                models_raw = data.get("data", [])
                                loaded = [m for m in models_raw if m.get("state") == "loaded"]
                                not_loaded = [m for m in models_raw if m.get("state") != "loaded"]
                                loaded_ids = [m["id"] for m in loaded]
                                _lm_studio_status = {
                                    "online": True,
                                    "model": loaded_ids[0] if loaded_ids else None,
                                    "loaded_models": loaded_ids,
                                    "all_models": [m["id"] for m in models_raw],
                                    "not_loaded_models": [m["id"] for m in not_loaded],
                                    "vram_used": None,
                                    "url": base,
                                    "checked_at": datetime.utcnow().isoformat(),
                                    "stats": _lm_studio_status.get("stats", {}),
                                    # Attach local GPU metrics (already polled by system poller)
                                    "gpu": _gpu_metrics if _gpu_metrics and _gpu_metrics.get("available") else None,
                                }
                                found = True
                                break
                except Exception:
                    continue
            if not found:
                _lm_studio_status = {
                    "online": False, "model": None, "loaded_models": [], "all_models": [],
                    "not_loaded_models": [], "vram_used": None, "url": None,
                    "checked_at": datetime.utcnow().isoformat(),
                    "stats": {},
                    "gpu": _gpu_metrics if _gpu_metrics and _gpu_metrics.get("available") else None,
                }
            await manager.broadcast("lmstudio_update", _lm_studio_status)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"LM Studio poller: {e}")


async def lmstudio_net_poller():
    """Poll the on-network LM Studio (RTX 4090, 10.10.10.180:1234).
    Also polls gpu_stats_server.py on port 18765 for VRAM / GPU / temp data.
    """
    global _lm_studio_net_status
    while True:
        try:
            await asyncio.sleep(15)
            timeout = aiohttp.ClientTimeout(total=5)

            # ── 1. Model list ───────────────────────────────────────────────
            models_ok  = False
            loaded_ids = []
            all_ids    = []
            not_loaded_ids = []
            try:
                url = f"{LM_STUDIO_NET_URL}/api/v0/models"
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            models_raw     = data.get("data", [])
                            loaded         = [m for m in models_raw if m.get("state") == "loaded"]
                            not_loaded     = [m for m in models_raw if m.get("state") != "loaded"]
                            loaded_ids     = [m["id"] for m in loaded]
                            all_ids        = [m["id"] for m in models_raw]
                            not_loaded_ids = [m["id"] for m in not_loaded]
                            models_ok = True
                        else:
                            raise Exception(f"HTTP {resp.status}")
            except Exception:
                pass  # handled below

            # ── 2. GPU stats from gpu_stats_server.py ───────────────────────
            gpu_data = None
            try:
                gpu_timeout = aiohttp.ClientTimeout(total=3)
                async with aiohttp.ClientSession(timeout=gpu_timeout) as gsession:
                    async with gsession.get(f"{LM_STUDIO_NET_GPU_URL}/gpu") as gresp:
                        if gresp.status == 200:
                            gpu_data = await gresp.json(content_type=None)
                            if not gpu_data.get("available"):
                                gpu_data = None
            except Exception:
                pass  # GPU stats server not running yet — that's fine

            # ── 3. Build status ─────────────────────────────────────────────
            if models_ok:
                _lm_studio_net_status = {
                    "online": True,
                    "model": loaded_ids[0] if loaded_ids else None,
                    "loaded_models": loaded_ids,
                    "all_models": all_ids,
                    "not_loaded_models": not_loaded_ids,
                    "vram_used": gpu_data.get("mem_used_mb") if gpu_data else None,
                    "checked_at": datetime.utcnow().isoformat(),
                    "url": LM_STUDIO_NET_URL,
                    "label": "LM NETWORK // 4090",
                    "gpu": gpu_data,
                }
            else:
                _lm_studio_net_status = {
                    "online": False, "model": None, "loaded_models": [], "all_models": [],
                    "not_loaded_models": [], "vram_used": None,
                    "checked_at": datetime.utcnow().isoformat(),
                    "url": LM_STUDIO_NET_URL, "label": "LM NETWORK // 4090",
                    "gpu": gpu_data,  # may still have GPU stats even if LM Studio is down
                }
            await manager.broadcast("lmstudio_net_update", _lm_studio_net_status)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"LM Studio NET poller: {e}")


async def telegram_poller():
    """
    Poll Telegram Bot API getMe endpoint to confirm bot is alive.
    Token is read from OPENCLAW_JSON at channels.telegram.botToken.
    """
    global _telegram_status

    # Do one immediate check, then repeat every 30 seconds
    async def _check():
        token = get_telegram_token()
        if not token:
            _telegram_status.update({
                "connected": False, "username": None,
                "error": "No botToken in openclaw.json",
                "checked_at": datetime.utcnow().isoformat(),
            })
            return

        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"https://api.telegram.org/bot{token}/getMe"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("ok"):
                            bot = data.get("result", {})
                            _telegram_status.update({
                                "connected": True,
                                "username": bot.get("username"),
                                "first_name": bot.get("first_name"),
                                "error": None,
                                "checked_at": datetime.utcnow().isoformat(),
                            })
                        else:
                            _telegram_status.update({
                                "connected": False,
                                "error": data.get("description", "API returned ok=false"),
                                "checked_at": datetime.utcnow().isoformat(),
                            })
                    else:
                        _telegram_status.update({
                            "connected": False,
                            "error": f"HTTP {resp.status}",
                            "checked_at": datetime.utcnow().isoformat(),
                        })
        except asyncio.TimeoutError:
            _telegram_status.update({
                "connected": False, "error": "Timeout",
                "checked_at": datetime.utcnow().isoformat(),
            })
        except Exception as e:
            _telegram_status.update({
                "connected": False, "error": str(e),
                "checked_at": datetime.utcnow().isoformat(),
            })

    # Initial check immediately
    try:
        await _check()
        await manager.broadcast("telegram_update", _telegram_status)
    except Exception:
        pass

    while True:
        try:
            await asyncio.sleep(30)
            await _check()
            await manager.broadcast("telegram_update", _telegram_status)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Telegram poller: {e}")


async def quicklaunch_watcher():
    while True:
        try:
            await asyncio.sleep(5)
            buttons = load_quick_launch()
            await manager.broadcast("quicklaunch_update", buttons)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Quick launch watcher: {e}")


async def heartbeat_checker():
    while True:
        try:
            await asyncio.sleep(30)
            agents = db.get_agents()
            now = datetime.utcnow()
            updated = []
            for agent in agents:
                if agent["status"] == "running" and agent["last_active"]:
                    try:
                        last = datetime.fromisoformat(agent["last_active"])
                        if (now - last).total_seconds() > 120:
                            db.upsert_agent(agent["name"], status="idle",
                                            last_action="Heartbeat timeout — marked idle")
                            updated.append(agent["name"])
                    except Exception:
                        pass
            if updated:
                await manager.broadcast("agent_update", db.get_agents())
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Heartbeat checker: {e}")


async def budget_reset_checker():
    while True:
        try:
            await asyncio.sleep(3600)
            budget = db.get_budget_summary()
            await manager.broadcast("budget_update", budget)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Budget reset checker: {e}")


async def activity_ticker():
    while True:
        try:
            await asyncio.sleep(5)
            last = db.get_last_activity()
            if last:
                await manager.broadcast("activity_tick", last)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Activity ticker: {e}")


async def tasks_periodic():
    """Push tasks update every 60 seconds as a fallback to watchdog."""
    while True:
        try:
            await asyncio.sleep(60)
            await manager.broadcast("tasks_update", get_tasks())
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Tasks periodic: {e}")


async def local_pc_broadcaster():
    """Poll Windows host resources via powershell.exe every 10 seconds."""
    global _local_pc_metrics
    # Initial fetch immediately
    try:
        _local_pc_metrics = await asyncio.get_event_loop().run_in_executor(
            None, get_local_pc_metrics
        )
        await manager.broadcast("local_pc_metrics", _local_pc_metrics)
    except Exception:
        pass
    while True:
        try:
            await asyncio.sleep(10)
            _local_pc_metrics = await asyncio.get_event_loop().run_in_executor(
                None, get_local_pc_metrics
            )
            await manager.broadcast("local_pc_metrics", _local_pc_metrics)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Local PC broadcaster: {e}")


def _log_external_spend(provider: str, amount: float) -> Optional[Dict]:
    """Record a synthetic ⚡ EXTERNAL routing entry for out-of-band API spend."""
    try:
        entry = db.add_routing_call(
            provider=provider,
            model_name="external/untracked",
            agent_name="⚡ EXTERNAL",
            tokens_in=0,
            tokens_out=0,
            cost_usd=round(amount, 6),
            latency_ms=0,
            actual_model="external/untracked",
        )
        logger.info(f"⚡ External spend logged — {provider}: ${amount:.4f}")
        return entry
    except Exception as e:
        logger.debug(f"Failed to log external spend: {e}")
        return None


async def provider_balance_poller():
    """Poll all provider balances every 60s.

    Providers attempted:
    • OpenRouter  – GET /api/v1/auth/key              (always works, free)
    • OpenAI      – GET /v1/dashboard/billing/subscription + /usage
                    (works for personal keys; sk-proj-* return 403 → silently skipped)
    • Anthropic   – GET /v1/account/credits  then /v1/organizations/balance
                    (endpoint varies; tries multiple; falls back to stored value)

    External spend detection:
    After each successful balance poll, compare the balance drop against tracked
    routing_calls spend in the same window.  Any gap is logged as ⚡ EXTERNAL so
    calls from VSCode Codex, Claude Code, direct API scripts etc. appear in the
    routing monitor automatically.
    """
    await asyncio.sleep(8)  # let service fully init first
    last_or_usage: float = -1.0
    last_balances: Dict[str, float] = {}   # provider → previous polled balance
    last_poll_ts:  datetime = datetime.utcnow()

    while True:
        poll_start   = last_poll_ts
        last_poll_ts = datetime.utcnow()
        new_entries: list = []

        try:
            async with aiohttp.ClientSession() as session:

                # ── OpenRouter ────────────────────────────────────────────────
                try:
                    or_key = get_api_key("openrouter")
                    if or_key:
                        async with session.get(
                            "https://openrouter.ai/api/v1/auth/key",
                            headers={"Authorization": f"Bearer {or_key}"},
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 200:
                                payload = await resp.json()
                                d       = payload.get("data", {})
                                usage   = float(d.get("usage") or 0)
                                limit   = d.get("limit")
                                rem     = d.get("limit_remaining")
                                if rem is not None:
                                    balance = round(float(rem), 4)
                                elif limit is not None:
                                    balance = round(float(limit) - usage, 4)
                                else:
                                    stored   = db.get_provider_balances().get("openrouter", {})
                                    prev_bal = float(stored.get("balance") or 0)
                                    if last_or_usage >= 0:
                                        delta   = max(0.0, usage - last_or_usage)
                                        balance = round(prev_bal - delta, 4)
                                    else:
                                        balance = prev_bal
                                last_or_usage = usage
                                # ── external spend detection ──────────────────
                                if "openrouter" in last_balances:
                                    bal_drop = round(last_balances["openrouter"] - balance, 6)
                                    if bal_drop > 0.001:
                                        tracked = db.get_provider_spend_since("openrouter", poll_start)
                                        ext = round(bal_drop - tracked, 6)
                                        if ext > 0.001:
                                            entry = _log_external_spend("openrouter", ext)
                                            if entry: new_entries.append(entry)
                                db.set_provider_balance("openrouter", balance)
                                last_balances["openrouter"] = balance
                                logger.debug(f"OpenRouter balance: ${balance}")
                except Exception as e:
                    logger.debug(f"OpenRouter balance poll error: {e}")

                # ── OpenAI ────────────────────────────────────────────────────
                try:
                    oa_key = get_api_key("openai")
                    if oa_key:
                        oa_balance: Optional[float] = None
                        # Attempt 1: classic billing/subscription (works for sk- user keys)
                        async with session.get(
                            "https://api.openai.com/v1/dashboard/billing/subscription",
                            headers={"Authorization": f"Bearer {oa_key}"},
                            timeout=aiohttp.ClientTimeout(total=8),
                        ) as sub_resp:
                            if sub_resp.status == 200:
                                sub        = await sub_resp.json()
                                hard_limit = float(sub.get("hard_limit_usd") or 0)
                                today      = datetime.utcnow().date()
                                start      = today.replace(day=1).isoformat()
                                end        = (today + timedelta(days=1)).isoformat()
                                async with session.get(
                                    f"https://api.openai.com/v1/dashboard/billing/usage"
                                    f"?start_date={start}&end_date={end}",
                                    headers={"Authorization": f"Bearer {oa_key}"},
                                    timeout=aiohttp.ClientTimeout(total=8),
                                ) as usg_resp:
                                    if usg_resp.status == 200:
                                        usg      = await usg_resp.json()
                                        used_usd = float(usg.get("total_usage") or 0) / 100.0
                                        oa_balance = round(hard_limit - used_usd, 4)
                            elif sub_resp.status == 403:
                                logger.debug("OpenAI billing/subscription: 403 (project key)")
                                # Attempt 2: newer credit grants endpoint
                                async with session.get(
                                    "https://api.openai.com/v1/dashboard/billing/credit_grants",
                                    headers={"Authorization": f"Bearer {oa_key}"},
                                    timeout=aiohttp.ClientTimeout(total=8),
                                ) as cg_resp:
                                    if cg_resp.status == 200:
                                        cg = await cg_resp.json()
                                        total   = float(cg.get("total_granted") or 0)
                                        used    = float(cg.get("total_used")    or 0)
                                        expired = float(cg.get("total_expired") or 0)
                                        oa_balance = round(total - used - expired, 4)
                        if oa_balance is not None:
                            # ── external spend detection ──────────────────────
                            if "openai" in last_balances:
                                bal_drop = round(last_balances["openai"] - oa_balance, 6)
                                if bal_drop > 0.001:
                                    tracked = db.get_provider_spend_since("openai", poll_start)
                                    ext = round(bal_drop - tracked, 6)
                                    if ext > 0.001:
                                        entry = _log_external_spend("openai", ext)
                                        if entry: new_entries.append(entry)
                            db.set_provider_balance("openai", oa_balance)
                            last_balances["openai"] = oa_balance
                            logger.info(f"OpenAI balance (API): ${oa_balance}")
                except Exception as e:
                    logger.debug(f"OpenAI balance poll error: {e}")

                # ── Anthropic ─────────────────────────────────────────────────
                try:
                    an_key = get_api_key("anthropic")
                    if an_key:
                        an_balance: Optional[float] = None
                        an_headers = {
                            "x-api-key":          an_key,
                            "anthropic-version":  "2023-06-01",
                            "content-type":       "application/json",
                        }
                        # Try known / plausible credit balance endpoints
                        for endpoint in [
                            "https://api.anthropic.com/v1/account/credits",
                            "https://api.anthropic.com/v1/organizations/balance",
                            "https://api.anthropic.com/v1/account",
                        ]:
                            try:
                                async with session.get(
                                    endpoint, headers=an_headers,
                                    timeout=aiohttp.ClientTimeout(total=8),
                                ) as an_resp:
                                    if an_resp.status == 200:
                                        an_data = await an_resp.json()
                                        # Field names vary by endpoint version
                                        bal = (
                                            an_data.get("credits_remaining")
                                            or an_data.get("credit_balance")
                                            or an_data.get("balance")
                                            or an_data.get("available_credit")
                                        )
                                        if bal is not None:
                                            an_balance = round(float(bal), 4)
                                            logger.info(f"Anthropic balance ({endpoint}): ${an_balance}")
                                            break
                                    elif an_resp.status in (404, 403):
                                        logger.debug(f"Anthropic {endpoint}: {an_resp.status}")
                            except Exception:
                                pass
                        if an_balance is not None:
                            # ── external spend detection ──────────────────────
                            if "anthropic" in last_balances:
                                bal_drop = round(last_balances["anthropic"] - an_balance, 6)
                                if bal_drop > 0.001:
                                    tracked = db.get_provider_spend_since("anthropic", poll_start)
                                    ext = round(bal_drop - tracked, 6)
                                    if ext > 0.001:
                                        entry = _log_external_spend("anthropic", ext)
                                        if entry: new_entries.append(entry)
                            db.set_provider_balance("anthropic", an_balance)
                            last_balances["anthropic"] = an_balance
                except Exception as e:
                    logger.debug(f"Anthropic balance poll error: {e}")

                # ── Google AI Studio ──────────────────────────────────────────
                # No billing balance API for AI Studio keys.
                # We validate the key is live via the models endpoint,
                # and track external spend via balance delta when available.
                try:
                    gg_key = get_api_key("google")
                    if gg_key:
                        # Key validation — models endpoint returns 200 if key is valid
                        async with session.get(
                            f"https://generativelanguage.googleapis.com/v1beta/models?key={gg_key}",
                            timeout=aiohttp.ClientTimeout(total=8),
                        ) as gg_resp:
                            if gg_resp.status == 200:
                                logger.debug("Google AI Studio key: valid")
                                # No balance endpoint available for AI Studio keys;
                                # stored balance is maintained manually.
                            elif gg_resp.status in (400, 403):
                                logger.warning(f"Google AI Studio key invalid: {gg_resp.status}")
                except Exception as e:
                    logger.debug(f"Google key validation error: {e}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Provider balance poller outer: {e}")

        # Broadcast balance + budget always; broadcast any new external entries too
        await manager.broadcast("provider_balances", db.get_provider_balances())
        await manager.broadcast("budget_update", db.get_budget_summary())
        for entry in new_entries:
            await manager.broadcast("routing_call", entry)
        await asyncio.sleep(60)


# ── Observer: periodic file writer ─────────────────────────────────────────────
async def observer_file_writer():
    """Write layout.json to OBSERVER_DIR every 30s so Arden can read it
    directly from the filesystem without needing to curl."""
    while True:
        try:
            await asyncio.sleep(30)
            budget = db.get_budget_summary()
            stats = db.get_routing_stats()
            metrics = _last_metrics or {}
            tasks_list = []
            try:
                for tf in sorted(TASKS_DIR.iterdir()):
                    if tf.suffix in ('.txt', '.md'):
                        tasks_list.append({
                            "name": tf.name,
                            "content": tf.read_text(errors="replace")[:500]
                        })
            except Exception:
                pass
            layout_data = {
                "timestamp": datetime.utcnow().isoformat(),
                "tiles": [
                    {"id": "avatar",       "label": "Arden Avatar",      "zone": "A"},
                    {"id": "aicore",       "label": "AI Core Status",    "zone": "A"},
                    {"id": "routing",      "label": "Routing Monitor",   "zone": "A"},
                    {"id": "jobs",         "label": "Active Jobs",       "zone": "A"},
                    {"id": "lmstudio",     "label": "LM Studio",         "zone": "B"},
                    {"id": "crons",        "label": "Scheduler",         "zone": "B"},
                    {"id": "logs",         "label": "Live Logs",         "zone": "B"},
                    {"id": "agents",       "label": "Agent Registry",    "zone": "B"},
                    {"id": "media",        "label": "Media Panel",       "zone": "C"},
                    {"id": "giphy",        "label": "Giphy",             "zone": "C"},
                    {"id": "notes",        "label": "Notes",             "zone": "C"},
                    {"id": "arden-chat",   "label": "Arden Neural Link", "zone": "D"},
                    {"id": "sessions",     "label": "Sessions",          "zone": "D"},
                    {"id": "chat",         "label": "General Chat",      "zone": "D"},
                    {"id": "lmstudio-net", "label": "LM Network",        "zone": "E"},
                    {"id": "rightpanel",   "label": "Context Panel",     "zone": "E"},
                ],
                "system": {
                    "cpu_percent":    metrics.get("cpu_percent", 0),
                    "memory_percent": metrics.get("memory_percent", 0),
                    "gpu_percent":    metrics.get("gpu_percent"),
                    "disk_percent":   metrics.get("disk_percent"),
                    "net_in":         metrics.get("net_in"),
                    "net_out":        metrics.get("net_out"),
                    "uptime":         metrics.get("uptime"),
                },
                "budget":       budget,
                "routingStats": stats,
                "tasks":        tasks_list,
                "agents":       db.get_agents(),
                "jobs":         db.get_cron_jobs(),
                "lmstudio":     _lm_studio_status,
                "snapshotAvailable": (OBSERVER_DIR / "current_view.png").exists(),
                "connectedBrowsers": len(manager.active),
            }
            layout_path = OBSERVER_DIR / "layout.json"
            async with aiofiles.open(layout_path, "w") as f:
                await f.write(json.dumps(layout_data, indent=2, default=str))

            # ── summary.txt — plain-English dashboard state ──────────
            sys = layout_data["system"]
            bud = layout_data.get("budget", {})
            lms = layout_data.get("lmstudio", {})
            gpu_info = (lms.get("gpu") or {}) if isinstance(lms, dict) else {}
            snap_exists = layout_data.get("snapshotAvailable", False)
            snap_status_path = OBSERVER_DIR / "snapshot_status.json"
            snap_line = "No snapshot yet"
            if snap_exists and snap_status_path.exists():
                try:
                    ss = json.loads(snap_status_path.read_text())
                    snap_line = (f"Yes — {ss.get('size_kb', '?')} KB, "
                                 f"taken {ss.get('saved_at', '?')}")
                except Exception:
                    snap_line = "Yes (status file unreadable)"
            elif snap_exists:
                snap_line = "Yes (no status file)"

            task_names = [t["name"] for t in layout_data.get("tasks", [])]
            agent_list = layout_data.get("agents", [])
            agent_statuses = {}
            for a in agent_list:
                s = a.get("status", "unknown")
                agent_statuses[s] = agent_statuses.get(s, 0) + 1
            agent_summary = ", ".join(f"{v} {k}" for k, v in agent_statuses.items())

            gpu_str = (f"{gpu_info['name']} @ {gpu_info.get('temp_c', '?')}°C, "
                       f"{gpu_info.get('util_pct', '?')}% util, "
                       f"{gpu_info.get('mem_used_mb', '?')}/{gpu_info.get('mem_total_mb', '?')} MB VRAM"
                       if gpu_info.get("name") else "N/A")

            summary_lines = [
                f"Dashboard Summary — {layout_data['timestamp']} UTC",
                f"Theme: Electric Obsidian",
                f"",
                f"System (WSL2):",
                f"  CPU:  {sys.get('cpu_percent', '?')}%",
                f"  RAM:  {sys.get('memory_percent', '?')}%",
                f"  GPU:  {gpu_str}",
                f"  Disk: {sys.get('disk_percent', '?') or '?'}%",
                f"",
                f"Budget:",
                f"  Spent:     ${bud.get('total_spent', 0):.2f} / ${bud.get('monthly_limit', 0):.2f}",
                f"  Remaining: ${bud.get('remaining', 0):.2f} ({bud.get('percent_used', 0):.1f}% used)",
                f"  Daily:     ${bud.get('daily_spent', 0):.2f} today",
                f"",
                f"Tasks ({len(task_names)}):",
            ]
            for tn in task_names:
                summary_lines.append(f"  - {tn}")
            summary_lines += [
                f"",
                f"Agents: {len(agent_list)} registered ({agent_summary})",
                f"Browsers: {layout_data.get('connectedBrowsers', 0)} connected",
                f"LM Studio: {'Online' if (lms.get('online') if isinstance(lms, dict) else False) else 'Offline'}",
                f"Last Snapshot: {snap_line}",
            ]

            summary_path = OBSERVER_DIR / "summary.txt"
            async with aiofiles.open(summary_path, "w") as f:
                await f.write("\n".join(summary_lines) + "\n")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Observer file writer: {e}")


# ── Cortex: periodic conversation ingest (every 4 hours) ──────────────────────
async def cortex_ingest_sender():
    """Flush buffered Neural Link conversations to Cortex /api/memory/ingest."""
    global _cortex_conv_buffer, _cortex_last_ingest
    while True:
        try:
            await asyncio.sleep(4 * 60 * 60)  # every 4 hours
            if not _cortex_conv_buffer:
                continue
            # Drain buffer
            batch = _cortex_conv_buffer[:]
            _cortex_conv_buffer = []
            payload = {
                "source": "neural_link",
                "conversations": batch,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{CORTEX_URL}/api/memory/ingest",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        _cortex_last_ingest = datetime.utcnow().isoformat()
                        log_entry = db.add_log(
                            f"Cortex ingest: {result.get('ingested', 0)} conversations "
                            f"→ {result.get('stored', 0)} memories",
                            "SUCCESS", "cortex")
                        await manager.broadcast("new_log", log_entry)
                        logger.info(f"Cortex ingest: {result}")
                    else:
                        # Put conversations back so we don't lose them
                        _cortex_conv_buffer = batch + _cortex_conv_buffer
                        logger.error(f"Cortex ingest failed: HTTP {resp.status}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Cortex ingest sender: {e}")


# ── Cortex: nightly digest + knowledge writer (1:00 AM UTC / ~9 PM EST) ───────
async def cortex_nightly_digest():
    """Fetch Arden's daily memory digest from Cortex and write knowledge MDs."""
    global _cortex_last_digest
    while True:
        try:
            # Calculate seconds until next 1:00 AM UTC (~9 PM EST)
            now = datetime.utcnow()
            target = now.replace(hour=1, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            wait_secs = (target - now).total_seconds()
            await asyncio.sleep(wait_secs)

            # Before fetching digest, flush any remaining conversations
            if _cortex_conv_buffer:
                batch = _cortex_conv_buffer[:]
                _cortex_conv_buffer.clear()
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{CORTEX_URL}/api/memory/ingest",
                            json={"source": "neural_link", "conversations": batch},
                            timeout=aiohttp.ClientTimeout(total=30),
                        ) as resp:
                            if resp.status == 200:
                                logger.info("Pre-digest flush: conversations ingested")
                except Exception as e:
                    logger.error(f"Pre-digest flush failed: {e}")
                    _cortex_conv_buffer.extend(batch)

            # Fetch digest since last check (or last 24h)
            since = _cortex_last_digest or (
                datetime.utcnow() - timedelta(hours=24)).isoformat()
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{CORTEX_URL}/api/memory/digest",
                    params={"since": since},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"Cortex digest failed: HTTP {resp.status}")
                        continue
                    digest = await resp.json()

            _cortex_last_digest = datetime.utcnow().isoformat()

            # Write the raw digest as JSON for Arden to reference
            digest_path = ARDEN_KNOWLEDGE / "latest_digest.json"
            async with aiofiles.open(digest_path, "w") as f:
                await f.write(json.dumps(digest, indent=2, default=str))

            # Write a human-readable daily knowledge file
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            md_path = ARDEN_KNOWLEDGE / f"digest_{date_str}.md"
            lines = [
                f"# Arden's Daily Digest — {date_str}",
                f"",
                f"*Generated from Cortex memory at {datetime.utcnow().isoformat()} UTC*",
                f"",
            ]
            memories = digest.get("memories", [])
            if not memories:
                lines.append("No new memories formed today.")
            else:
                # Group by type
                by_type = {}
                for mem in memories:
                    mtype = mem.get("type", "unknown")
                    by_type.setdefault(mtype, []).append(mem)

                for mtype, mems in by_type.items():
                    lines.append(f"## {mtype.title()} ({len(mems)})")
                    lines.append("")
                    for m in mems:
                        summary = m.get("summary", m.get("content", ""))
                        tags = m.get("tags", [])
                        conf = m.get("confidence", "")
                        lines.append(f"- {summary}")
                        if tags:
                            lines.append(f"  *Tags: {', '.join(tags)}*")
                        if conf:
                            lines.append(f"  *Confidence: {conf}*")
                    lines.append("")

            lines.append("---")
            lines.append(f"*Source: Cortex @ {CORTEX_URL} | Memories: {len(memories)}*")

            async with aiofiles.open(md_path, "w") as f:
                await f.write("\n".join(lines) + "\n")

            log_entry = db.add_log(
                f"Cortex nightly digest: {len(memories)} memories → {md_path.name}",
                "SUCCESS", "cortex")
            await manager.broadcast("new_log", log_entry)
            logger.info(f"Nightly digest written: {md_path}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Cortex nightly digest: {e}")


# ── Lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_quick_launch()
    db.set_budget_limit(MONTHLY_BUDGET)

    loop = asyncio.get_event_loop()

    tasks = [
        asyncio.create_task(metrics_broadcaster()),
        asyncio.create_task(avatar_updater()),
        asyncio.create_task(lmstudio_poller()),
        asyncio.create_task(lmstudio_net_poller()),
        asyncio.create_task(telegram_poller()),
        asyncio.create_task(quicklaunch_watcher()),
        asyncio.create_task(heartbeat_checker()),
        asyncio.create_task(budget_reset_checker()),
        asyncio.create_task(activity_ticker()),
        asyncio.create_task(tasks_periodic()),
        asyncio.create_task(local_pc_broadcaster()),
        asyncio.create_task(provider_balance_poller()),
        asyncio.create_task(observer_file_writer()),
        asyncio.create_task(cortex_ingest_sender()),
        asyncio.create_task(cortex_nightly_digest()),
    ]

    # Watchdog observer for tasks folder
    observer = None
    if WATCHDOG_AVAILABLE:
        try:
            handler = TaskFolderHandler(loop)
            observer = Observer()
            observer.schedule(handler, str(TASKS_DIR), recursive=False)
            observer.start()
            logger.info(f"Watchdog watching tasks dir: {TASKS_DIR}")
        except Exception as e:
            logger.warning(f"Watchdog setup failed: {e}")
    else:
        logger.warning("watchdog not installed — tasks folder changes will only refresh every 60s")

    db.add_log("Command Center online — all systems initializing", "SUCCESS", "system")
    logger.info(f"Command Center started on {HOST}:{PORT}")
    yield

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if observer:
        observer.stop()
        observer.join(timeout=2)


# ── FastAPI App ────────────────────────────────────────────────────────────────
app = FastAPI(title="Arden // Command Center", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# ─── Security headers ────────────────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response

# ─── Auth middleware (only active when CC_PASSWORD is set) ────────────────────
@app.middleware("http")
async def auth_gate(request: Request, call_next):
    if not AUTH_ENABLED:
        return await call_next(request)
    path = request.url.path
    # Allow public paths (login, static, root page)
    if path in _PUBLIC_EXACT or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await call_next(request)
    # Check Authorization header: Bearer <token>
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
    # Also accept ?token= query param (for WebSocket upgrades)
    if not token:
        token = request.query_params.get("token", "")
    # Also accept cc_token cookie
    if not token:
        token = request.cookies.get("cc_token", "")
    if not token or not _jwt_decode(token):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)

# ─── Auth endpoints ──────────────────────────────────────────────────────────
@app.post("/api/auth/login")
async def auth_login(payload: dict):
    pw = payload.get("password", "")
    if not AUTH_ENABLED:
        return {"token": "", "message": "Auth disabled"}
    if not _check_password(pw):
        raise HTTPException(401, "Invalid password")
    token = _jwt_encode({
        "sub": "admin",
        "iat": int(time.time()),
        "exp": int(time.time()) + CC_TOKEN_HOURS * 3600,
    })
    response = JSONResponse({"token": token, "expires_in": CC_TOKEN_HOURS * 3600})
    response.set_cookie(
        "cc_token", token, httponly=True, samesite="strict",
        max_age=CC_TOKEN_HOURS * 3600,
    )
    return response

@app.get("/api/auth/check")
async def auth_check(request: Request):
    if not AUTH_ENABLED:
        return {"authenticated": True, "auth_required": False}
    token = request.cookies.get("cc_token", "") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    payload = _jwt_decode(token) if token else None
    return {"authenticated": payload is not None, "auth_required": True}

@app.post("/api/auth/logout")
async def auth_logout():
    response = JSONResponse({"message": "Logged out"})
    response.delete_cookie("cc_token")
    return response

if AVATARS_DIR.exists():
    app.mount("/avatars", StaticFiles(directory=str(AVATARS_DIR)), name="avatars")

STATIC_DIR = Path(__file__).parent / "static"


# ── WebSocket ──────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Auth check for WebSocket (token via query param)
    if AUTH_ENABLED:
        token = ws.query_params.get("token", "")
        if not token or not _jwt_decode(token):
            await ws.close(code=1008, reason="Unauthorized")
            return
    await manager.connect(ws)
    try:
        metrics_now = _last_metrics or {}
        gpu_now = _gpu_metrics or get_gpu_metrics()
        budget_now = db.get_budget_summary()
        await ws.send_text(json.dumps({
            "type": "init",
            "data": {
                "agents":        db.get_agents(),
                "logs":          db.get_logs(limit=100),
                "routing":       db.get_routing_calls(limit=200),
                "budget":        budget_now,
                "crons":         db.get_cron_jobs(),
                "avatar":        avatar_manager.get_state(),
                "system":        {**metrics_now, "gpu": gpu_now},
                "lmstudio":      _lm_studio_status,
                "lmstudio_net":  _lm_studio_net_status,
                "telegram":      _telegram_status,
                "quicklaunch":   _quick_launch_buttons,
                "uploads":       db.get_uploads(),
                "notes":         db.get_notes(),
                "last_activity": db.get_last_activity(),
                "routing_stats": db.get_routing_stats(),
                "tasks":         get_tasks(),
                "local_pc":      _local_pc_metrics,
                "provider_balances": db.get_provider_balances(),
                "provider_registry": get_provider_registry(),
                "telemetry": {
                    "globalSeverity": compute_global_severity(
                        metrics_now.get("cpu_percent", 0) or 0,
                        metrics_now.get("memory_percent", 0) or 0,
                        budget_now.get("percent_used", 0) or 0,
                    ),
                },
            },
            "ts": datetime.utcnow().isoformat(),
        }))
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong", "ts": datetime.utcnow().isoformat()}))
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(ws)


# ── Frontend ───────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>index.html not found</h1>", status_code=404)


# ── API: System ────────────────────────────────────────────────────────────────
@app.get("/api/system")
async def get_system_metrics():
    return _last_metrics or metrics_collector.collect().to_dict()


# ── API: Agents ────────────────────────────────────────────────────────────────
@app.get("/api/agents")
async def get_agents():
    return db.get_agents()

@app.post("/api/agents/register")
async def register_agent(payload: dict):
    name = payload.get("name")
    if not name:
        raise HTTPException(400, "name is required")
    agent = db.upsert_agent(
        name=name,
        display_name=payload.get("display_name"),
        status=payload.get("status", "idle"),
        last_action=payload.get("last_action"),
        metadata=payload.get("metadata"),
    )
    if payload.get("status") == "running":
        _processing_agents.add(name)
    else:
        _processing_agents.discard(name)
    log = db.add_log(f"Agent registered: {name} ({payload.get('status', 'idle')})", "INFO", "system")
    await manager.broadcast("agent_update", db.get_agents())
    await manager.broadcast("new_log", log)
    return agent

@app.get("/api/agents/{agent_name}/logs")
async def get_agent_logs(agent_name: str, limit: int = 20):
    return db.get_agent_logs(agent_name, limit)

@app.post("/api/agents/{agent_name}/status")
async def update_agent_status(agent_name: str, payload: dict):
    status = payload.get("status", "idle")
    agent = db.upsert_agent(name=agent_name, status=status, last_action=payload.get("last_action"))
    if status == "running":
        _processing_agents.add(agent_name)
    else:
        _processing_agents.discard(agent_name)
    await manager.broadcast("agent_update", db.get_agents())
    return agent


# ── API: Logs ──────────────────────────────────────────────────────────────────
@app.get("/api/logs")
async def get_logs(limit: int = 200, level: str = None, agent: str = None):
    return db.get_logs(limit=limit, level=level, agent_name=agent)

@app.post("/api/logs")
async def add_log(payload: dict):
    message = payload.get("message", "")
    if not message:
        raise HTTPException(400, "message is required")
    log = db.add_log(message, payload.get("level", "INFO"), payload.get("agent_name", "system"))
    await manager.broadcast("new_log", log)
    return log

@app.delete("/api/logs")
async def clear_logs():
    db.clear_logs()
    await manager.broadcast("logs_cleared", {})
    db.add_log("Logs cleared by operator", "INFO", "system")
    return {"status": "ok"}


# ── API: Routing ───────────────────────────────────────────────────────────────
@app.get("/api/routing")
async def get_routing(limit: int = 50):
    return db.get_routing_calls(limit)

@app.post("/api/routing")
async def add_routing_call(payload: dict):
    call = db.add_routing_call(
        provider=payload.get("provider", "unknown"),
        model_name=payload.get("model_name", "unknown"),
        agent_name=payload.get("agent_name", "unknown"),
        tokens_in=int(payload.get("tokens_in", 0)),
        tokens_out=int(payload.get("tokens_out", 0)),
        cost_usd=float(payload.get("cost_usd", 0.0)),
        latency_ms=int(payload.get("latency_ms", 0)),
        actual_model=payload.get("actual_model"),
    )
    budget = db.get_budget_summary()
    _add_routing_log(call)  # add to SSE ring buffer
    await manager.broadcast("routing_call", call)
    await manager.broadcast("budget_update", budget)
    return call

@app.get("/api/routing/stats")
async def get_routing_stats():
    return db.get_routing_stats()


# ── API: Budget ────────────────────────────────────────────────────────────────
@app.get("/api/budget")
async def get_budget():
    return db.get_budget_summary()

@app.put("/api/budget/config")
async def set_budget(payload: dict):
    monthly = float(payload.get("monthly_limit", 60.0))
    daily = payload.get("daily_limit")
    db.set_budget_limit(monthly, float(daily) if daily else None)
    budget = db.get_budget_summary()
    await manager.broadcast("budget_update", budget)
    db.add_log(f"Budget limit updated: ${monthly:.2f}/month", "INFO", "system")
    return budget

@app.get("/api/budget/balances")
async def get_balances():
    """Return all manually-set provider bucket balances."""
    return db.get_provider_balances()

def _parse_router_log_savings(cloud_in: float = 1.0, cloud_out: float = 3.0) -> dict:
    """Parse the LLM router's request log for local model calls (lmstudio/ollama).
    Returns {mtd_calls, mtd_tin, mtd_tout, all_calls, all_tin, all_tout}.
    The router log lives at workspace/logs/router-requests.log.
    Each line is a JSON object with 'provider' and 'estimated_tokens_in'.
    """
    import json as _json
    from datetime import date as _date
    log_path = "/home/mikegg/.openclaw/workspace/logs/router-requests.log"
    period_start = _date.today().replace(day=1).isoformat()  # YYYY-MM-01
    result = {"mtd_calls": 0, "mtd_tin": 0, "mtd_tout": 0,
              "all_calls": 0, "all_tin": 0, "all_tout": 0}
    try:
        with open(log_path, "r", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    # Router uses Python dict repr (single quotes, True/False/None)
                    import ast as _ast
                    entry = _ast.literal_eval(raw)
                except Exception:
                    continue
                if entry.get("provider") not in ("lmstudio", "ollama", "local", "lmstudio-net"):
                    continue
                tin  = int(entry.get("estimated_tokens_in",  0) or 0)
                tout = int(entry.get("estimated_tokens_out", tin) or tin)  # fallback = same as in
                ts   = entry.get("timestamp", "")  # may or may not be present
                result["all_calls"] += 1
                result["all_tin"]   += tin
                result["all_tout"]  += tout
                # MTD: check timestamp field if present, else count all
                if not ts or ts[:10] >= period_start:
                    result["mtd_calls"] += 1
                    result["mtd_tin"]   += tin
                    result["mtd_tout"]  += tout
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"Router log savings parse error: {e}")
    return result

@app.get("/api/budget/savings")
async def get_savings():
    """Estimated savings from local LM vs equivalent cloud cost.
    Combines command-center DB calls (provider=local/lmstudio/ollama)
    with calls logged directly by the LLM router (router-requests.log).
    """
    CLOUD_IN  = 1.0   # $ per 1M input tokens (mid-tier cloud baseline)
    CLOUD_OUT = 3.0   # $ per 1M output tokens
    base = db.get_savings_summary(cloud_in_rate=CLOUD_IN, cloud_out_rate=CLOUD_OUT)
    router = _parse_router_log_savings(cloud_in=CLOUD_IN, cloud_out=CLOUD_OUT)

    def _merge(base_section: dict, r_calls: int, r_tin: int, r_tout: int) -> dict:
        calls = base_section["calls"] + r_calls
        tin   = base_section["tokens_in"]  + r_tin
        tout  = base_section["tokens_out"] + r_tout
        est   = round((tin * CLOUD_IN + tout * CLOUD_OUT) / 1_000_000, 4)
        return {"calls": calls, "tokens_in": tin, "tokens_out": tout,
                "tokens_total": tin + tout, "actual_cost": 0.0,
                "estimated_cloud_cost": est, "saved": est}

    return {
        "mtd":      _merge(base["mtd"],      router["mtd_calls"], router["mtd_tin"], router["mtd_tout"]),
        "all_time": _merge(base["all_time"], router["all_calls"], router["all_tin"], router["all_tout"]),
        "cloud_rate": base["cloud_rate"],
    }

@app.put("/api/budget/balance")
async def set_balance(payload: dict):
    """Upsert a provider's bucket balance for manual reconciliation."""
    provider = payload.get("provider", "").strip().lower()
    balance  = float(payload.get("balance", 0.0))
    if not provider:
        return {"error": "provider required"}, 400
    db.set_provider_balance(provider, balance)
    return {"status": "saved", "provider": provider, "balance": balance}


# ── API: Cron Jobs ─────────────────────────────────────────────────────────────
@app.get("/api/crons")
async def get_crons():
    return db.get_cron_jobs()

@app.post("/api/crons")
async def register_cron(payload: dict):
    name = payload.get("name")
    schedule = payload.get("schedule")
    if not name or not schedule:
        raise HTTPException(400, "name and schedule are required")
    job = db.upsert_cron_job(name=name, schedule=schedule,
                             description=payload.get("description"),
                             command=payload.get("command"))
    await manager.broadcast("cron_update", db.get_cron_jobs())
    return job

@app.post("/api/crons/{job_name}/trigger")
async def trigger_cron(job_name: str):
    jobs = db.get_cron_jobs()
    job = next((j for j in jobs if j["name"] == job_name), None)
    if not job:
        raise HTTPException(404, f"Cron job '{job_name}' not found")
    db.update_cron_run(job_name, "RUNNING")
    await manager.broadcast("cron_update", db.get_cron_jobs())
    log = db.add_log(f"Cron job manually triggered: {job_name}", "INFO", "system")
    await manager.broadcast("new_log", log)

    async def run_job():
        await asyncio.sleep(2)
        db.update_cron_run(job_name, "SUCCESS",
                           f"Manual trigger completed at {datetime.utcnow().isoformat()}")
        await manager.broadcast("cron_update", db.get_cron_jobs())
        await manager.broadcast("new_log",
                                db.add_log(f"Cron job completed: {job_name}", "SUCCESS", "system"))

    asyncio.create_task(run_job())
    return {"status": "triggered", "job": job_name}


# ── API: Avatar ────────────────────────────────────────────────────────────────
@app.get("/api/avatar")
async def get_avatar():
    return avatar_manager.get_state()

@app.post("/api/avatar/reload")
async def reload_avatars():
    state = avatar_manager.reload()
    await manager.broadcast("avatar_update", state)
    db.add_log("Avatar images reloaded", "INFO", "system")
    return state

@app.post("/api/avatar/cycle")
async def cycle_avatar():
    state = avatar_manager.force_cycle()
    await manager.broadcast("avatar_update", state)
    return state


# ── API: Providers ─────────────────────────────────────────────────────────────
@app.get("/api/providers")
async def get_providers():
    stats = db.get_routing_stats()
    providers = []
    for name, color in [("anthropic","#ff00c8"),("openai","#00f0ff"),
                        ("openrouter","#ffaa00"),("local","#00ff88")]:
        s = stats.get(name, {})
        last_call = s.get("last_call")
        is_active = False
        if last_call:
            try:
                ts = datetime.fromisoformat(last_call)
                is_active = (datetime.utcnow() - ts).total_seconds() < 86400
            except Exception:
                pass
        providers.append({
            "name": name, "color": color, "active": is_active,
            "calls_today": s.get("calls_today", 0),
            "tokens_today": s.get("tokens_today", 0),
            "cost_today": round(s.get("cost_today", 0) or 0, 4),
            "last_call": last_call,
        })
    return providers


# ── API: LM Studio ─────────────────────────────────────────────────────────────
@app.get("/api/lmstudio")
async def get_lmstudio():
    return _lm_studio_status


# ── API: Telegram ──────────────────────────────────────────────────────────────
@app.get("/api/telegram")
async def get_telegram():
    return _telegram_status

@app.post("/api/telegram/event")
async def telegram_event(payload: dict):
    global _telegram_status
    _telegram_status.update({
        "connected":      payload.get("connected", True),
        "last_message":   payload.get("last_message"),
        "messages_today": payload.get("messages_today", 0),
        "checked_at":     datetime.utcnow().isoformat(),
    })
    await manager.broadcast("telegram_update", _telegram_status)
    return _telegram_status


# ── API: File Upload ───────────────────────────────────────────────────────────
MAX_UPLOAD_MB   = int(os.getenv("MAX_UPLOAD_MB", "100"))
ALLOWED_UPLOAD_EXT = {
    ".pdf", ".txt", ".csv", ".json", ".md", ".yaml", ".yml", ".toml",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".py", ".js", ".ts", ".html", ".css", ".sh", ".env",
    ".log", ".xml", ".zip", ".tar", ".gz",
}

@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    _rate_check(f"upload:{request.client.host}", max_per_min=10)
    if not file.filename:
        raise HTTPException(400, "No file provided")
    safe_name = "".join(c for c in file.filename if c.isalnum() or c in "._- ").strip()
    if not safe_name:
        raise HTTPException(400, "Invalid filename")
    # File type validation
    ext = Path(safe_name).suffix.lower()
    if ext and ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, f"File type '{ext}' not allowed")
    dest = UPLOADS_DIR / safe_name
    if dest.exists():
        dest = UPLOADS_DIR / f"{dest.stem}_{int(time.time())}{dest.suffix}"
        safe_name = dest.name
    size = 0
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    async with aiofiles.open(dest, "wb") as f:
        while True:
            chunk = await file.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                await f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds {MAX_UPLOAD_MB}MB limit")
            await f.write(chunk)
    record = db.add_upload(safe_name, file.filename, size, str(dest))
    log = db.add_log(f"File uploaded: {file.filename} ({size:,} bytes)", "SUCCESS", "system")
    await manager.broadcast("upload_complete", record)
    await manager.broadcast("new_log", log)
    return record

@app.get("/api/uploads")
async def get_uploads(limit: int = 10):
    return db.get_uploads(limit)


# ── API: Observer (Arden's Eyes) ──────────────────────────────────────────────

@app.post("/api/observer/snapshot")
async def save_observer_snapshot(payload: dict):
    """Receive a base64 PNG screenshot of the dashboard from the frontend."""
    import base64 as _b64
    data = payload.get("image", "")
    if not data:
        raise HTTPException(400, "No image data provided")
    # Strip data-URL prefix if present
    if "," in data:
        data = data.split(",", 1)[1]
    try:
        img_bytes = _b64.b64decode(data)
    except Exception:
        raise HTTPException(400, "Invalid base64 image data")
    # Size guard – 10 MB max
    if len(img_bytes) > 10 * 1024 * 1024:
        raise HTTPException(413, "Screenshot exceeds 10 MB limit")
    # Save as current_view.png (always the latest)
    current_path = OBSERVER_DIR / "current_view.png"
    async with aiofiles.open(current_path, "wb") as f:
        await f.write(img_bytes)
    # Also save a timestamped copy
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    ts_path = OBSERVER_DIR / f"snapshot_{ts}.png"
    async with aiofiles.open(ts_path, "wb") as f:
        await f.write(img_bytes)
    # Housekeeping — keep last 20 timestamped snapshots
    snaps = sorted(OBSERVER_DIR.glob("snapshot_*.png"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for old in snaps[20:]:
        old.unlink(missing_ok=True)
    size_kb = len(img_bytes) / 1024
    log_entry = db.add_log(
        f"Observer snapshot saved ({size_kb:.0f} KB)", "INFO", "observer")
    await manager.broadcast("new_log", log_entry)
    # Write status file so Arden can check via filesystem
    status = {"status": "ok", "file": str(current_path),
              "size_kb": round(size_kb, 1), "timestamp": ts,
              "saved_at": datetime.utcnow().isoformat()}
    async with aiofiles.open(OBSERVER_DIR / "snapshot_status.json", "w") as f:
        await f.write(json.dumps(status, indent=2))
    return status


@app.get("/api/observer/snapshot")
async def get_observer_snapshot():
    """Serve the latest dashboard screenshot as PNG."""
    from fastapi.responses import FileResponse
    current_path = OBSERVER_DIR / "current_view.png"
    if not current_path.exists():
        raise HTTPException(404, "No snapshot available — capture one first")
    return FileResponse(current_path, media_type="image/png")


@app.get("/api/observer/snapshots")
async def list_observer_snapshots(limit: int = 20):
    """List available timestamped snapshots."""
    snaps = sorted(OBSERVER_DIR.glob("snapshot_*.png"),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    return [{"name": s.name,
             "size_kb": round(s.stat().st_size / 1024, 1),
             "modified": datetime.fromtimestamp(s.stat().st_mtime).isoformat()}
            for s in snaps]


@app.post("/api/observer/trigger")
async def trigger_observer_snapshot():
    """Ask any connected browser to capture a snapshot via WebSocket.
    Returns immediately — the browser will POST the image back to
    /api/observer/snapshot asynchronously."""
    connected = len(manager.active)
    if connected == 0:
        return {
            "status": "no_browser",
            "message": "No browser is connected via WebSocket. "
                       "Open the dashboard in a browser first, "
                       "or use /api/observer/layout for data-only access.",
            "snapshotAvailable": (OBSERVER_DIR / "current_view.png").exists(),
        }
    await manager.broadcast("trigger_browser_snapshot", {
        "requested_at": datetime.utcnow().isoformat()
    })
    return {
        "status": "triggered",
        "message": f"Snapshot request sent to {connected} connected browser(s). "
                   "The image will be saved to imports/observer/current_view.png "
                   "within a few seconds.",
        "connected_browsers": connected,
    }


@app.get("/api/observer/layout")
async def get_observer_layout():
    """Enhanced telemetry with tile layout — Arden's spatial awareness map."""
    budget = db.get_budget_summary()
    stats = db.get_routing_stats()
    metrics = _last_metrics or {}
    # Gather tasks
    tasks_list = []
    try:
        for tf in sorted(TASKS_DIR.iterdir()):
            if tf.suffix in ('.txt', '.md'):
                tasks_list.append({
                    "name": tf.name,
                    "content": tf.read_text(errors="replace")[:500]
                })
    except Exception:
        pass
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "tiles": [
            {"id": "avatar",       "label": "Arden Avatar",      "zone": "A"},
            {"id": "aicore",       "label": "AI Core Status",    "zone": "A"},
            {"id": "routing",      "label": "Routing Monitor",   "zone": "A"},
            {"id": "jobs",         "label": "Active Jobs",       "zone": "A"},
            {"id": "lmstudio",     "label": "LM Studio",         "zone": "B"},
            {"id": "crons",        "label": "Scheduler",         "zone": "B"},
            {"id": "logs",         "label": "Live Logs",         "zone": "B"},
            {"id": "agents",       "label": "Agent Registry",    "zone": "B"},
            {"id": "media",        "label": "Media Panel",       "zone": "C"},
            {"id": "giphy",        "label": "Giphy",             "zone": "C"},
            {"id": "notes",        "label": "Notes",             "zone": "C"},
            {"id": "arden-chat",   "label": "Arden Neural Link", "zone": "D"},
            {"id": "sessions",     "label": "Sessions",          "zone": "D"},
            {"id": "chat",         "label": "General Chat",      "zone": "D"},
            {"id": "lmstudio-net", "label": "LM Network",        "zone": "E"},
            {"id": "rightpanel",   "label": "Context Panel",     "zone": "E"},
        ],
        "system": {
            "cpu_percent":    metrics.get("cpu_percent", 0),
            "memory_percent": metrics.get("memory_percent", 0),
            "gpu_percent":    metrics.get("gpu_percent"),
            "disk_percent":   metrics.get("disk_percent"),
            "net_in":         metrics.get("net_in"),
            "net_out":        metrics.get("net_out"),
            "uptime":         metrics.get("uptime"),
        },
        "budget":       budget,
        "routingStats": stats,
        "tasks":        tasks_list,
        "agents":       db.get_agents(),
        "jobs":         db.get_cron_jobs(),
        "lmstudio":     _lm_studio_status,
        "snapshotAvailable": (OBSERVER_DIR / "current_view.png").exists(),
    }


# ── API: Cortex (Arden's Memory) ─────────────────────────────────────────────

@app.post("/api/cortex/ingest")
async def cortex_manual_ingest():
    """Manually flush buffered conversations to Cortex now."""
    global _cortex_conv_buffer, _cortex_last_ingest
    if not _cortex_conv_buffer:
        return {"status": "empty", "message": "No conversations buffered"}
    batch = _cortex_conv_buffer[:]
    _cortex_conv_buffer = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{CORTEX_URL}/api/memory/ingest",
                json={"source": "neural_link", "conversations": batch},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    _cortex_last_ingest = datetime.utcnow().isoformat()
                    log_entry = db.add_log(
                        f"Cortex manual ingest: {result.get('ingested', 0)} conversations "
                        f"→ {result.get('stored', 0)} memories",
                        "SUCCESS", "cortex")
                    await manager.broadcast("new_log", log_entry)
                    return result
                else:
                    _cortex_conv_buffer = batch + _cortex_conv_buffer
                    raise HTTPException(502, f"Cortex returned HTTP {resp.status}")
    except HTTPException:
        raise
    except Exception as e:
        _cortex_conv_buffer = batch + _cortex_conv_buffer
        raise HTTPException(502, f"Cortex ingest failed: {str(e)[:120]}")


@app.get("/api/cortex/digest")
async def cortex_manual_digest(since: str = "", write: bool = False):
    """Manually fetch Arden's memory digest from Cortex.
    Pass ?write=true to also write knowledge MD files (like the nightly job does).
    """
    global _cortex_last_digest
    if not since:
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{CORTEX_URL}/api/memory/digest",
                params={"since": since},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    raise HTTPException(502, f"Cortex returned HTTP {resp.status}")
                digest = await resp.json()

        if write and digest.get("memories"):
            _cortex_last_digest = datetime.utcnow().isoformat()
            # Write latest_digest.json
            (ARDEN_KNOWLEDGE / "latest_digest.json").write_text(
                json.dumps(digest, indent=2), encoding="utf-8"
            )
            # Write dated MD
            today = datetime.utcnow().strftime("%Y-%m-%d")
            md_lines = [f"# Arden Memory Digest — {today}\n"]
            md_lines.append(f"Source: Cortex @ {CORTEX_URL}\n")
            md_lines.append(f"Total memories: {digest.get('total', 0)}\n")
            for mtype in ("episodic", "semantic", "procedural"):
                items = digest.get("memories", {}).get(mtype, [])
                if items:
                    md_lines.append(f"\n## {mtype.title()} ({len(items)})\n")
                    for m in items:
                        tags = ", ".join(m.get("tags", []))
                        md_lines.append(
                            f"- **{m.get('summary', 'No summary')}**"
                            f"  (confidence: {m.get('confidence', '?')}, tags: {tags})\n"
                        )
            md_path = ARDEN_KNOWLEDGE / f"digest_{today}.md"
            md_path.write_text("".join(md_lines), encoding="utf-8")
            digest["knowledge_written"] = str(md_path)

        return digest
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Cortex digest failed: {str(e)[:120]}")


@app.get("/api/cortex/status")
async def cortex_status():
    """Check Cortex connectivity and Arden's memory state."""
    status = {
        "cortex_url": CORTEX_URL,
        "buffered_conversations": len(_cortex_conv_buffer),
        "last_ingest": _cortex_last_ingest,
        "last_digest": _cortex_last_digest or "never",
        "knowledge_dir": str(ARDEN_KNOWLEDGE),
    }
    # Try to reach Cortex
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{CORTEX_URL}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    status["cortex_health"] = "online"
                    # Also get memory stats
                    async with session.get(
                        f"{CORTEX_URL}/api/memory/stats",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as mr:
                        if mr.status == 200:
                            status["memory_stats"] = await mr.json()
                else:
                    status["cortex_health"] = f"unhealthy (HTTP {resp.status})"
    except Exception as e:
        status["cortex_health"] = f"unreachable ({str(e)[:80]})"
    # Count knowledge files
    try:
        knowledge_files = list(ARDEN_KNOWLEDGE.glob("digest_*.md"))
        status["knowledge_files"] = len(knowledge_files)
        if knowledge_files:
            latest = max(knowledge_files, key=lambda p: p.stat().st_mtime)
            status["latest_knowledge"] = latest.name
    except Exception:
        status["knowledge_files"] = 0
    return status


# ── API: Notes ─────────────────────────────────────────────────────────────────
@app.get("/api/notes")
async def get_notes():
    return {"content": db.get_notes()}

@app.post("/api/notes")
async def save_notes(payload: dict):
    content = payload.get("content", "")
    db.save_notes(content)
    # Also export to import folder when requested (Quick Notes SAVE button)
    if payload.get("export_to_import", False):
        try:
            notes_file = UPLOADS_DIR / "workspace-notes.md"
            notes_file.write_text(content, encoding="utf-8")
            logger.info(f"Notes exported to {notes_file}")
        except Exception as e:
            logger.warning(f"Notes export to import folder failed: {e}")
    return {"status": "saved"}


# ── API: Quick Launch ──────────────────────────────────────────────────────────
@app.get("/api/quicklaunch")
async def get_quicklaunch():
    return load_quick_launch()


# ── API: Tasks ─────────────────────────────────────────────────────────────────
@app.get("/api/tasks")
async def get_tasks_endpoint():
    return get_tasks()

@app.get("/api/tasks/open-folder")
async def open_tasks_folder():
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # Try xdg-open (works in WSL2 with wslg/wslopen), fall back to explorer.exe
        for cmd in [["xdg-open", str(TASKS_DIR)],
                    ["explorer.exe", str(TASKS_DIR)]]:
            try:
                subprocess.Popen(cmd)
                return {"status": "ok", "path": str(TASKS_DIR)}
            except FileNotFoundError:
                continue
    except Exception as e:
        return {"status": "error", "message": str(e), "path": str(TASKS_DIR)}
    return {"status": "ok", "path": str(TASKS_DIR)}


# ── API: GPU ───────────────────────────────────────────────────────────────────
@app.get("/api/gpu")
async def get_gpu():
    return _gpu_metrics or get_gpu_metrics()


# ── API: Local PC (Windows host via powershell.exe) ────────────────────────────
@app.get("/api/system/local-pc")
async def get_local_pc():
    """Return latest Windows host CPU/RAM metrics polled via powershell.exe."""
    return _local_pc_metrics


# ── API: Telemetry Layer ───────────────────────────────────────────────────────
@app.get("/api/telemetry/overview")
async def telemetry_overview():
    """Unified overview: severity, active provider, budgets, routing, jobs."""
    budget = db.get_budget_summary()
    stats = db.get_routing_stats()
    metrics = _last_metrics or {}
    cpu = metrics.get("cpu_percent", 0) or 0
    ram = metrics.get("memory_percent", 0) or 0
    budget_pct = budget.get("percent_used", 0) or 0
    # Active provider = one with most calls in last 24h
    active = None
    max_calls = 0
    for p, s in stats.items():
        c = s.get("calls_today", 0) or 0
        if c > max_calls:
            max_calls = c
            active = p
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "globalSeverity": compute_global_severity(cpu, ram, budget_pct),
        "activeProvider": active,
        "budget": budget,
        "routingStats": stats,
        "jobs": db.get_cron_jobs(),
        "lmstudio": _lm_studio_status,
    }

@app.get("/api/telemetry/providers")
async def telemetry_providers():
    """Per-provider telemetry: call counts, latency, tokens, cost, key status."""
    stats = db.get_routing_stats()
    registry = get_provider_registry()
    result = {}
    for name in ["anthropic", "openai", "openrouter", "local", "google"]:
        s = stats.get(name, {})
        last_call = s.get("last_call")
        active = False
        if last_call:
            try:
                ts = datetime.fromisoformat(last_call)
                active = (datetime.utcnow() - ts).total_seconds() < 300  # active in last 5 min
            except Exception:
                pass
        result[name] = {
            "lastCallAt": last_call,
            "active": active,
            "reqCount24h": s.get("calls_today", 0) or 0,
            "reqCount1h":  s.get("calls_1h", 0) or 0,
            "avgLatencyMs": s.get("avg_latency") or None,
            "errorRate": s.get("error_rate") or None,
            "tokens24h": s.get("tokens_today", 0) or 0,
            "cost24h": round(s.get("cost_today", 0) or 0, 5),
            "mainKey": registry.get(name, {}).get("main_key", "missing"),
            "buckets": registry.get(name, {}).get("buckets", {}),
            "noTelemetry": (s.get("calls_today", 0) or 0) == 0,
        }
    return result

@app.get("/api/telemetry/system/local")
async def telemetry_system_local():
    """LOCAL GAMING PC host resources (Windows host via powershell)."""
    return _local_pc_metrics

@app.get("/api/telemetry/system/agent")
async def telemetry_system_agent():
    """ARDEN AGENT NODE resources (Linux/WSL2 process metrics)."""
    m = _last_metrics or {}
    return {
        "cpu_percent": m.get("cpu_percent", 0),
        "memory_percent": m.get("memory_percent", 0),
        "memory_used_gb": m.get("memory_used_gb"),
        "memory_total_gb": m.get("memory_total_gb"),
        "disk": m.get("disk"),
        "network": m.get("network"),
        "uptime_s": m.get("uptime_s"),
        "gpu": _gpu_metrics,
        "updated_at": datetime.utcnow().isoformat(),
    }

@app.get("/api/telemetry/logs")
async def telemetry_logs(level: str = None, limit: int = 100):
    """Recent system logs with optional level filter."""
    return db.get_logs(limit=limit, level=level)

@app.get("/api/telemetry/routing/calls")
async def telemetry_routing_calls(limit: int = 200):
    """Last N routing call events (real instrumented calls)."""
    calls = db.get_routing_calls(min(limit, 200))
    return calls

@app.get("/api/telemetry/lmstudio")
async def telemetry_lmstudio():
    """LM Studio full status including loaded/downloaded models, stats."""
    return _lm_studio_status

@app.get("/api/telemetry/registry")
async def telemetry_registry():
    """Provider registry with key presence (never exposes actual keys)."""
    return get_provider_registry()

from fastapi.responses import StreamingResponse
import asyncio as _asyncio

@app.get("/api/telemetry/stream")
async def telemetry_stream(request: Request):
    """
    Server-Sent Events stream for real-time telemetry.
    Emits: routing_call, system_metrics, lmstudio_update, budget_update
    """
    queue = _asyncio.Queue(maxsize=50)
    _sse_clients.append(queue)

    async def event_generator():
        try:
            # Send initial snapshot
            snapshot = {
                "type": "snapshot",
                "data": {
                    "budget": db.get_budget_summary(),
                    "routing": db.get_routing_stats(),
                    "lmstudio": _lm_studio_status,
                    "system": _last_metrics,
                },
                "ts": datetime.utcnow().isoformat(),
            }
            yield f"data: {json.dumps(snapshot)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    yield f"data: {json.dumps({'type': 'ping', 'ts': datetime.utcnow().isoformat()})}\n\n"
        except Exception:
            pass
        finally:
            try:
                _sse_clients.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ── API: Giphy Proxy ────────────────────────────────────────────────────────────
@app.get("/api/giphy/search")
async def giphy_search_proxy(q: str = "", limit: int = 12, offset: int = 0):
    """Proxy Giphy search using server-side GIPHY_API_KEY env var."""
    api_key = os.getenv("GIPHY_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "GIPHY_KEY_MISSING: set GIPHY_API_KEY in .env")
    if not q:
        raise HTTPException(400, "q (search query) is required")
    try:
        url = (
            f"https://api.giphy.com/v1/gifs/search"
            f"?api_key={api_key}&q={q}&limit={limit}&offset={offset}&rating=g&bundle=messaging_non_clips"
        )
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200:
                    # Extract just what we need (avoid sending huge payloads)
                    gifs = []
                    for g in data.get("data", []):
                        images = g.get("images", {})
                        preview = images.get("fixed_height_small", images.get("downsized", {}))
                        original = images.get("original", {})
                        gifs.append({
                            "id": g.get("id"),
                            "title": g.get("title", ""),
                            "url": preview.get("url", ""),
                            "mp4": preview.get("mp4", ""),
                            "original_url": original.get("url", ""),
                            "width": int(preview.get("width", 0) or 0),
                            "height": int(preview.get("height", 0) or 0),
                        })
                    return {"gifs": gifs, "total": data.get("pagination", {}).get("total_count", 0)}
                raise HTTPException(resp.status, f"Giphy API error: {data.get('message', 'unknown')}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Giphy proxy error: {e}")
        raise HTTPException(502, f"Giphy proxy failed: {e}")


# ── API: LM Studio (correct endpoints) ─────────────────────────────────────────
@app.get("/api/lmstudio/models")
async def lmstudio_models():
    """List all models from LM Studio (loaded and not-loaded)."""
    if not _lm_studio_status.get("online"):
        raise HTTPException(503, "LM Studio is offline")
    base = _lm_studio_status.get("url") or LM_STUDIO_URL
    url = f"{base}/api/v0/models"
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)
                return data
    except Exception as e:
        raise HTTPException(502, f"LM Studio request failed: {e}")

@app.post("/api/lmstudio/load")
async def lmstudio_load(payload: dict):
    """Load a model in LM Studio — POST /api/v1/models/load with {model: id}."""
    model_id = payload.get("model", "").strip()
    if not model_id:
        raise HTTPException(400, "model field is required")
    base = _lm_studio_status.get("url") or LM_STUDIO_URL
    url = f"{base}/api/v1/models/load"
    try:
        timeout = aiohttp.ClientTimeout(total=30)  # loading can take time
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json={"model": model_id}) as resp:
                data = await resp.json(content_type=None)
                db.add_log(f"LM Studio LOAD: {model_id}", "INFO", "lmstudio")
                return {"status": "ok", "model": model_id, "response": data}
    except Exception as e:
        raise HTTPException(502, f"LM Studio load failed: {e}")

@app.post("/api/lmstudio/unload")
async def lmstudio_unload(payload: dict):
    """
    Unload a model from LM Studio.
    CORRECT endpoint: POST /api/v1/models/unload with {instance_id: id}
    NOT: DELETE /v1/models/<id>  (that endpoint silently fails)
    """
    instance_id = payload.get("instance_id", "").strip()
    if not instance_id:
        raise HTTPException(400, "instance_id field is required")
    base = _lm_studio_status.get("url") or LM_STUDIO_URL
    url = f"{base}/api/v1/models/unload"
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json={"instance_id": instance_id}) as resp:
                data = await resp.json(content_type=None)
                db.add_log(f"LM Studio UNLOAD: {instance_id}", "INFO", "lmstudio")
                return {"status": "ok", "instance_id": instance_id, "response": data}
    except Exception as e:
        raise HTTPException(502, f"LM Studio unload failed: {e}")


# ── API: LM Studio NETWORK (RTX 4090 on Proxmox, 10.10.10.180:1234) ─────────────
@app.get("/api/lmstudio-net")
async def get_lmstudio_net():
    return _lm_studio_net_status

@app.get("/api/lmstudio-net/models")
async def lmstudio_net_models():
    """List models from the on-network LM Studio (4090)."""
    url = f"{LM_STUDIO_NET_URL}/api/v0/models"
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                return await resp.json(content_type=None)
    except Exception as e:
        raise HTTPException(502, f"LM Studio NET unreachable: {e}")

@app.post("/api/lmstudio-net/load")
async def lmstudio_net_load(payload: dict):
    model_id = payload.get("model", "").strip()
    if not model_id:
        raise HTTPException(400, "model field is required")
    url = f"{LM_STUDIO_NET_URL}/api/v1/models/load"
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json={"model": model_id}) as resp:
                data = await resp.json(content_type=None)
                db.add_log(f"LM Studio NET LOAD: {model_id}", "INFO", "lmstudio-net")
                return {"status": "ok", "model": model_id, "response": data}
    except Exception as e:
        raise HTTPException(502, f"LM Studio NET load failed: {e}")

@app.post("/api/lmstudio-net/unload")
async def lmstudio_net_unload(payload: dict):
    instance_id = payload.get("instance_id", "").strip()
    if not instance_id:
        raise HTTPException(400, "instance_id field is required")
    url = f"{LM_STUDIO_NET_URL}/api/v1/models/unload"
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json={"instance_id": instance_id}) as resp:
                data = await resp.json(content_type=None)
                db.add_log(f"LM Studio NET UNLOAD: {instance_id}", "INFO", "lmstudio-net")
                return {"status": "ok", "instance_id": instance_id, "response": data}
    except Exception as e:
        raise HTTPException(502, f"LM Studio NET unload failed: {e}")


# ── API: Tasks CRUD (enhanced) ─────────────────────────────────────────────────
@app.delete("/api/tasks/{filename}")
async def delete_task(filename: str):
    """Delete a task file."""
    safe = "".join(c for c in filename if c.isalnum() or c in "._- ")
    path = TASKS_DIR / safe
    if not path.exists():
        raise HTTPException(404, f"Task not found: {safe}")
    path.unlink()
    await manager.broadcast("tasks_update", get_tasks())
    return {"status": "deleted", "filename": safe}

@app.put("/api/tasks/{filename}/done")
async def mark_task_done(filename: str):
    """Rename task file to add done- prefix."""
    safe = "".join(c for c in filename if c.isalnum() or c in "._- ")
    path = TASKS_DIR / safe
    if not path.exists():
        raise HTTPException(404, f"Task not found: {safe}")
    if not safe.lower().startswith("done-") and not safe.lower().startswith("done_"):
        stem = path.stem
        new_name = f"done-{stem}{path.suffix}"
        new_path = TASKS_DIR / new_name
        path.rename(new_path)
        await manager.broadcast("tasks_update", get_tasks())
        return {"status": "marked_done", "filename": new_name}
    return {"status": "already_done", "filename": safe}

@app.post("/api/tasks/create")
async def create_task_from_note(payload: dict):
    """Create a task file from a note. Used by Quick Notes 'create task' feature."""
    title = payload.get("title", "").strip()
    content = payload.get("content", "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    # Sanitize filename
    safe_title = "".join(c if c.isalnum() or c in " -_" else "-" for c in title)
    safe_title = safe_title.strip("-").strip()[:80]
    filename = f"{safe_title}.md"
    path = TASKS_DIR / filename
    # Handle collisions
    if path.exists():
        filename = f"{safe_title}-{int(time.time())}.md"
        path = TASKS_DIR / filename
    path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
    log = db.add_log(f"Task created from note: {title}", "SUCCESS", "system")
    await manager.broadcast("tasks_update", get_tasks())
    await manager.broadcast("new_log", log)
    return {"status": "created", "filename": filename, "path": str(path)}


# ── Simple rate limiter (in-memory, per-endpoint) ─────────────────────────────
_rate_buckets: Dict[str, list] = {}

def _rate_check(key: str, max_per_min: int = 15):
    """Raise 429 if limit exceeded. Cleans entries older than 60s."""
    now = time.time()
    bucket = _rate_buckets.setdefault(key, [])
    _rate_buckets[key] = [t for t in bucket if now - t < 60]
    if len(_rate_buckets[key]) >= max_per_min:
        raise HTTPException(429, f"Rate limit: max {max_per_min} requests/min")
    _rate_buckets[key].append(now)

# ── API: Chat ──────────────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat_proxy(request: Request, payload: dict):
    """Proxy chat requests to Anthropic / OpenAI / OpenRouter."""
    _rate_check(f"chat:{request.client.host}", max_per_min=15)
    provider  = payload.get("provider", "anthropic").lower()
    model     = payload.get("model", "claude-3-5-haiku-20241022")
    messages  = payload.get("messages", [])
    api_key   = payload.get("api_key") or get_api_key(provider)

    if not api_key and provider not in ("local", "lmstudio", "lmstudio-net"):
        raise HTTPException(400, f"No API key found for provider '{provider}'. "
                                 "Set the key in ~/.bashrc or openclaw.json.")
    if not messages:
        raise HTTPException(400, "messages array is required")

    try:
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:

            # ── Anthropic ──────────────────────────────────────────────────────
            if provider == "anthropic":
                url = "https://api.anthropic.com/v1/messages"
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                }
                body = {"model": model, "max_tokens": 2048, "messages": messages}
                t0 = time.time()
                async with session.post(url, headers=headers, json=body) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status == 200:
                        text = (data.get("content") or [{}])[0].get("text", "")
                        tokens = data.get("usage", {})
                        tin  = tokens.get("input_tokens", 0)
                        tout = tokens.get("output_tokens", 0)
                        latency_ms = int((time.time() - t0) * 1000)
                        cost = _calc_cost("anthropic", model, tin, tout)
                        call = db.add_routing_call(
                            provider="anthropic", model_name=model,
                            agent_name=payload.get("agent_name", "chat"),
                            tokens_in=tin, tokens_out=tout, cost_usd=cost,
                            latency_ms=latency_ms,
                        )
                        _add_routing_log(call)
                        await manager.broadcast("routing_call", call)
                        await manager.broadcast("budget_update", db.get_budget_summary())
                        return {"reply": text, "model": model,
                                "tokens_in": tin, "tokens_out": tout}
                    raise HTTPException(resp.status,
                        data.get("error", {}).get("message", f"Anthropic API error {resp.status}"))

            # ── OpenAI / OpenRouter ────────────────────────────────────────────
            elif provider in ("openai", "openrouter"):
                url = ("https://api.openai.com/v1/chat/completions"
                       if provider == "openai"
                       else "https://openrouter.ai/api/v1/chat/completions")
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                }
                if provider == "openrouter":
                    headers["HTTP-Referer"] = "http://localhost:3000"
                    headers["X-Title"] = "Arden Command Center"
                body = {"model": model, "messages": messages}
                t0 = time.time()
                async with session.post(url, headers=headers, json=body) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status == 200:
                        choice = (data.get("choices") or [{}])[0]
                        text = choice.get("message", {}).get("content", "")
                        usage = data.get("usage", {})
                        tin  = usage.get("prompt_tokens", 0)
                        tout = usage.get("completion_tokens", 0)
                        latency_ms = int((time.time() - t0) * 1000)
                        # Use actual cost from OpenRouter when available, else per-model table
                        actual_or_cost = (data.get("usage") or {}).get("cost") if provider == "openrouter" else None
                        cost = _calc_cost(provider, model, tin, tout, actual_or_cost)
                        call = db.add_routing_call(
                            provider=provider, model_name=model,
                            agent_name=payload.get("agent_name", "chat"),
                            tokens_in=tin, tokens_out=tout, cost_usd=cost,
                            latency_ms=latency_ms,
                        )
                        _add_routing_log(call)
                        await manager.broadcast("routing_call", call)
                        await manager.broadcast("budget_update", db.get_budget_summary())
                        return {"reply": text, "model": model,
                                "tokens_in": tin, "tokens_out": tout}
                    err = data.get("error", {})
                    msg = err.get("message") or str(err) or f"HTTP {resp.status}"
                    raise HTTPException(resp.status, msg)

            # ── Local LM Studio ───────────────────────────────────────────────
            elif provider in ("local", "lmstudio"):
                # Find active LM Studio URL from poller state
                lm_base = _lm_studio_status.get("url") if _lm_studio_status.get("online") else None
                if not lm_base:
                    # Try direct IP as fallback
                    for _base in _build_lmstudio_urls():
                        try:
                            async with aiohttp.ClientSession() as _s:
                                async with _s.get(f"{_base}/api/v0/models",
                                    timeout=aiohttp.ClientTimeout(total=3)) as _r:
                                    if _r.status == 200:
                                        lm_base = _base
                                        break
                        except Exception:
                            continue
                if not lm_base:
                    raise HTTPException(503, "LM Studio is offline or unreachable")
                # Use provided model, or the first loaded model, or let LM Studio pick
                lm_model = model or (_lm_studio_status.get("model") or "")
                url = f"{lm_base}/v1/chat/completions"
                body = {"messages": messages}
                if lm_model:
                    body["model"] = lm_model
                t0 = time.time()
                async with session.post(url, json=body,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status == 200:
                        choice = (data.get("choices") or [{}])[0]
                        text = choice.get("message", {}).get("content", "")
                        usage = data.get("usage", {})
                        tin  = usage.get("prompt_tokens", 0)
                        tout = usage.get("completion_tokens", 0)
                        actual_model = data.get("model", lm_model)
                        latency_ms = int((time.time() - t0) * 1000)
                        call = db.add_routing_call(
                            provider="local",
                            model_name=lm_model or "lmstudio",
                            agent_name=payload.get("agent_name", "chat"),
                            tokens_in=tin, tokens_out=tout,
                            cost_usd=0.0,  # local inference = free
                            latency_ms=latency_ms,
                            actual_model=actual_model,
                        )
                        _add_routing_log(call)
                        await manager.broadcast("routing_call", call)
                        await manager.broadcast("budget_update", db.get_budget_summary())
                        return {"reply": text, "model": actual_model,
                                "tokens_in": tin, "tokens_out": tout}
                    err_body = data.get("error", {})
                    raise HTTPException(resp.status,
                        err_body.get("message", f"LM Studio error {resp.status}"))

            # ── LM Studio NETWORK (RTX 4090 on Proxmox) ──────────────────────────
            elif provider == "lmstudio-net":
                lm_model = model or (_lm_studio_net_status.get("model") or "")
                url = f"{LM_STUDIO_NET_URL}/v1/chat/completions"
                body = {"messages": messages}
                if lm_model:
                    body["model"] = lm_model
                t0 = time.time()
                async with session.post(url, json=body,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status == 200:
                        choice = (data.get("choices") or [{}])[0]
                        text = choice.get("message", {}).get("content", "")
                        usage = data.get("usage", {})
                        tin  = usage.get("prompt_tokens", 0)
                        tout = usage.get("completion_tokens", 0)
                        actual_model = data.get("model", lm_model)
                        latency_ms = int((time.time() - t0) * 1000)
                        call = db.add_routing_call(
                            provider="lmstudio-net",
                            model_name=lm_model or "lmstudio-net",
                            agent_name=payload.get("agent_name", "chat"),
                            tokens_in=tin, tokens_out=tout,
                            cost_usd=0.0,
                            latency_ms=latency_ms,
                            actual_model=actual_model,
                        )
                        _add_routing_log(call)
                        await manager.broadcast("routing_call", call)
                        await manager.broadcast("budget_update", db.get_budget_summary())
                        return {"reply": text, "model": actual_model,
                                "tokens_in": tin, "tokens_out": tout}
                    err_body = data.get("error", {})
                    raise HTTPException(resp.status,
                        err_body.get("message", f"LM Studio NET error {resp.status}"))

            # ── Google AI Studio (Gemini) ──────────────────────────────────────────
            elif provider == "google":
                # Google GenerativeAI API — NOT OpenAI-compatible
                url = (
                    f"https://generativelanguage.googleapis.com"
                    f"/v1beta/models/{model}:generateContent?key={api_key}"
                )
                headers = {"content-type": "application/json"}
                # Convert messages: OpenAI "assistant" role → Google "model" role
                gg_contents = []
                for msg in messages:
                    role = "model" if msg.get("role") == "assistant" else msg.get("role", "user")
                    gg_contents.append({
                        "role": role,
                        "parts": [{"text": msg.get("content", "")}],
                    })
                body = {
                    "contents": gg_contents,
                    "generationConfig": {"maxOutputTokens": 2048},
                }
                t0 = time.time()
                async with session.post(url, headers=headers, json=body) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status == 200:
                        candidate  = (data.get("candidates") or [{}])[0]
                        parts      = (candidate.get("content") or {}).get("parts") or [{}]
                        text       = parts[0].get("text", "")
                        usage      = data.get("usageMetadata", {})
                        tin        = usage.get("promptTokenCount", 0)
                        tout       = usage.get("candidatesTokenCount", 0)
                        latency_ms = int((time.time() - t0) * 1000)
                        cost = _calc_cost("google", model, tin, tout)
                        call = db.add_routing_call(
                            provider="google", model_name=model,
                            agent_name=payload.get("agent_name", "chat"),
                            tokens_in=tin, tokens_out=tout, cost_usd=cost,
                            latency_ms=latency_ms,
                        )
                        _add_routing_log(call)
                        await manager.broadcast("routing_call", call)
                        await manager.broadcast("budget_update", db.get_budget_summary())
                        return {"reply": text, "call": call,
                                "tokens_in": tin, "tokens_out": tout}
                    err = data.get("error") or {}
                    raise HTTPException(resp.status,
                        err.get("message", f"Google AI error {resp.status}"))

            else:
                raise HTTPException(400, f"Unknown provider '{provider}'. Use: anthropic, openai, openrouter, local, google, lmstudio-net")

    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(504, "Chat request timed out (90s)")
    except Exception as e:
        logger.error(f"Chat proxy error: {e}")
        raise HTTPException(500, str(e))


# ── API: Giphy ─────────────────────────────────────────────────────────────────
@app.get("/api/giphy")
async def giphy_proxy(q: str = "", limit: int = 25):
    """Proxy Giphy trending / search. Requires GIPHY_API_KEY in env."""
    key = os.getenv("GIPHY_API_KEY")
    if not key:
        return {
            "error": "No GIPHY_API_KEY configured — add it to command_center/.env and restart",
            "gifs": [],
        }
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if q:
                url = (
                    f"https://api.giphy.com/v1/gifs/search"
                    f"?api_key={key}&q={q}&limit={limit}&rating=g&lang=en"
                )
            else:
                url = (
                    f"https://api.giphy.com/v1/gifs/trending"
                    f"?api_key={key}&limit={limit}&rating=g"
                )
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200:
                    return {"error": f"Giphy API error {resp.status}", "gifs": []}
                gifs = []
                for g in data.get("data", []):
                    imgs  = g.get("images", {})
                    thumb = (imgs.get("fixed_height_small") or
                             imgs.get("fixed_height") or
                             imgs.get("original") or {})
                    gifs.append({
                        "id":    g["id"],
                        "url":   thumb.get("url", ""),
                        "title": g.get("title", ""),
                    })
                return {"gifs": gifs}
    except Exception as e:
        logger.debug(f"Giphy proxy error: {e}")
        return {"error": str(e), "gifs": []}


# ── API: ElevenLabs TTS ────────────────────────────────────────────────────────
@app.post("/api/tts")
async def text_to_speech(payload: dict):
    """Proxy text → speech via ElevenLabs. Returns audio/mpeg stream."""
    text     = payload.get("text", "").strip()
    voice_id = (payload.get("voice_id")
                or os.getenv("ELEVENLABS_VOICE_ID", "")
                or "XrExE9yKIg1WjnnlVkGX")   # default: Matilda (knowledgeable, professional)
    model_id = payload.get("model_id", "eleven_turbo_v2_5")
    key      = os.getenv("ELEVENLABS_API_KEY")

    if not key:
        raise HTTPException(400, "No ELEVENLABS_API_KEY configured")
    if not text:
        raise HTTPException(400, "text is required")

    url     = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": key, "content-type": "application/json", "accept": "audio/mpeg"}
    body    = {
        "text":     text,
        "model_id": model_id,
        "voice_settings": {
            "stability":        0.5,
            "similarity_boost": 0.75,
            "style":            0.0,
            "use_speaker_boost": True,
        },
    }
    try:
        from fastapi.responses import Response as FResp
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=body) as resp:
                if resp.status == 200:
                    audio = await resp.read()
                    return FResp(content=audio, media_type="audio/mpeg")
                err = await resp.json(content_type=None)
                raise HTTPException(resp.status, str(err.get("detail", err)))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── API: ElevenLabs Voices ─────────────────────────────────────────────────────
@app.get("/api/voices")
async def list_elevenlabs_voices():
    """List ElevenLabs voices available on this account."""
    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        return {"voices": [], "error": "No ELEVENLABS_API_KEY configured"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": key},
            ) as resp:
                data = await resp.json(content_type=None)
                voices = sorted([
                    {"id":       v["voice_id"],
                     "name":     v["name"],
                     "category": v.get("category", "")}
                    for v in data.get("voices", [])
                ], key=lambda x: x["name"])
                return {"voices": voices}
    except Exception as e:
        return {"voices": [], "error": str(e)}


# ── API: YouTube Data ──────────────────────────────────────────────────────────
@app.get("/api/youtube/trending")
async def youtube_trending(maxResults: int = 20, regionCode: str = "US"):
    """Fetch trending videos via YouTube Data API v3."""
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "GOOGLE_API_KEY not set")
    url = (
        f"https://www.googleapis.com/youtube/v3/videos"
        f"?part=snippet&chart=mostPopular"
        f"&maxResults={maxResults}&regionCode={regionCode}&key={api_key}"
    )
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                if "error" in data:
                    raise HTTPException(400, data["error"].get("message", "YouTube API error"))
                items = []
                for item in data.get("items", []):
                    sn = item.get("snippet", {})
                    items.append({
                        "id":        item["id"],
                        "title":     sn.get("title", ""),
                        "channel":   sn.get("channelTitle", ""),
                        "thumb":     (sn.get("thumbnails", {}).get("medium") or
                                      sn.get("thumbnails", {}).get("default") or {}).get("url", ""),
                    })
                return {"items": items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/youtube/search")
async def youtube_search(q: str, maxResults: int = 20):
    """Search YouTube videos via Data API v3."""
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "GOOGLE_API_KEY not set")
    url = (
        f"https://www.googleapis.com/youtube/v3/search"
        f"?part=snippet&type=video&q={q}"
        f"&maxResults={maxResults}&key={api_key}"
    )
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                if "error" in data:
                    raise HTTPException(400, data["error"].get("message", "YouTube API error"))
                items = []
                for item in data.get("items", []):
                    sn = item.get("snippet", {})
                    vid = item.get("id", {}).get("videoId", "")
                    if not vid:
                        continue
                    items.append({
                        "id":      vid,
                        "title":   sn.get("title", ""),
                        "channel": sn.get("channelTitle", ""),
                        "thumb":   (sn.get("thumbnails", {}).get("medium") or
                                    sn.get("thumbnails", {}).get("default") or {}).get("url", ""),
                    })
                return {"items": items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── API: Arden Neural Link (proxies to OpenClaw gateway) ──────────────────────
def _build_dashboard_context() -> str:
    """Build a concise snapshot of live dashboard state for Arden."""
    lines = ["[DASHBOARD LIVE SNAPSHOT]"]
    now = datetime.now()
    lines.append(f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}")

    # ── Tasks ──
    try:
        tasks = get_tasks()
        pending = [t for t in tasks if not t["done"]]
        done    = [t for t in tasks if t["done"]]
        lines.append(f"\n## TASKS ({len(pending)} pending, {len(done)} done)")
        for t in pending:
            lines.append(f"  [ ] {t['title']}  ({t['modified_str']})")
            if t.get("content", "").strip():
                preview = t["content"].strip()[:120].replace("\n", " ")
                lines.append(f"      {preview}")
        for t in done:
            lines.append(f"  [x] {t['title']}")
    except Exception as e:
        lines.append(f"\n## TASKS  (error: {e})")

    # ── Budget ──
    try:
        budget = db.get_budget_summary()
        balances = db.get_provider_balances()
        lines.append(f"\n## BUDGET")
        lines.append(f"  Monthly limit: ${budget.get('monthly_limit', 0):.2f}")
        lines.append(f"  Spent this month: ${budget.get('total_spent', 0):.2f}")
        lines.append(f"  Remaining: ${budget.get('remaining', 0):.2f}")
        for prov, bal in (balances or {}).items():
            lines.append(f"  {prov}: ${bal:.2f}")
    except Exception:
        pass

    # ── Notes ──
    try:
        notes = db.get_notes()
        if notes and notes.strip():
            preview = notes.strip()[:300].replace("\n", " | ")
            lines.append(f"\n## QUICK NOTES\n  {preview}")
    except Exception:
        pass

    # ── System health ──
    try:
        m = _last_metrics or {}
        gpu = _gpu_metrics or {}
        lines.append(f"\n## SYSTEM (WSL2 Arden Node)")
        if m:
            lines.append(f"  CPU: {m.get('cpu_percent',0):.1f}%  RAM: {m.get('memory_percent',0):.1f}% ({m.get('memory_used_gb',0):.1f}/{m.get('memory_total_gb',0):.0f} GB)  Uptime: {int((m.get('uptime_s',0))/3600)}h")
        if gpu:
            lines.append(f"  GPU: {gpu.get('name','?')} — {gpu.get('util_pct',0):.0f}% util, {gpu.get('temp_c',0)}°C, {gpu.get('mem_used_mb',0):.0f}/{gpu.get('mem_total_mb',0):.0f} MB VRAM")
        pc = _local_pc_metrics or {}
        if pc.get("available"):
            lines.append(f"  Local PC: {pc.get('cpu_name','')} — CPU {pc.get('cpu_pct',0):.0f}%  RAM {pc.get('ram_used_pct',0):.0f}%")
    except Exception:
        pass

    # ── Agents ──
    try:
        agents = db.get_agents()
        if agents:
            lines.append(f"\n## AGENTS ({len(agents)} registered)")
            for a in agents[:8]:
                lines.append(f"  {a['display_name'] or a['name']}: {a.get('status','?')}  last: {a.get('last_action','')}")
    except Exception:
        pass

    # ── Cron jobs ──
    try:
        crons = db.get_cron_jobs()
        if crons:
            lines.append(f"\n## SCHEDULER ({len(crons)} jobs)")
            for c in crons:
                lines.append(f"  {c['name']}: {c.get('last_status','?')} — last: {c.get('last_run','never')}")
    except Exception:
        pass

    # ── Recent uploads ──
    try:
        uploads = db.get_uploads(limit=5)
        if uploads:
            lines.append(f"\n## RECENT UPLOADS")
            for u in uploads:
                sz = u.get("size", 0)
                szk = f"{sz/1024:.1f}KB" if sz < 1048576 else f"{sz/1048576:.1f}MB"
                lines.append(f"  {u.get('original_name', u.get('filename','?'))} ({szk})")
    except Exception:
        pass

    # ── LM Studio / LM Network ──
    try:
        lm = _lm_studio_status or {}
        lmn = _lm_studio_net_status or {}
        if lm.get("online"):
            models = ", ".join(lm.get("loaded_models", [])) or lm.get("model", "?")
            lines.append(f"\n## LM STUDIO: ONLINE — {models}")
        else:
            lines.append(f"\n## LM STUDIO: OFFLINE")
        if lmn.get("online"):
            models = ", ".join(lmn.get("loaded_models", [])) or lmn.get("model", "?")
            lines.append(f"## LM NETWORK (4090): ONLINE — {models}")
        else:
            lines.append(f"## LM NETWORK (4090): OFFLINE")
    except Exception:
        pass

    # ── Providers ──
    try:
        stats = db.get_routing_stats()
        if stats:
            lines.append(f"\n## PROVIDER STATS (24h)")
            for prov, s in stats.items():
                if s.get("calls_today", 0):
                    lines.append(f"  {prov}: {s['calls_today']} calls, ${s.get('cost_today',0):.4f}")
    except Exception:
        pass

    # ── Arden's Cortex Knowledge ──
    try:
        # Include latest digest summary if available
        digest_path = ARDEN_KNOWLEDGE / "latest_digest.json"
        if digest_path.exists():
            digest = json.loads(digest_path.read_text())
            memories = digest.get("memories", [])
            if memories:
                lines.append(f"\n## CORTEX MEMORY (latest digest: {len(memories)} memories)")
                for m in memories[:10]:
                    mtype = m.get("type", "?")
                    summary = m.get("summary", m.get("content", ""))[:150]
                    lines.append(f"  [{mtype}] {summary}")
        # Include recent knowledge MDs (titles only)
        knowledge_files = sorted(ARDEN_KNOWLEDGE.glob("digest_*.md"), reverse=True)[:5]
        if knowledge_files:
            lines.append(f"\n## MY KNOWLEDGE FILES ({len(list(ARDEN_KNOWLEDGE.glob('digest_*.md')))} total)")
            for kf in knowledge_files:
                lines.append(f"  - {kf.name}")
    except Exception:
        pass

    # ── Cortex Status ──
    try:
        lines.append(f"\n## CORTEX ({CORTEX_URL})")
        lines.append(f"  Last ingest: {_cortex_last_ingest}")
        lines.append(f"  Last digest: {_cortex_last_digest or 'never'}")
        lines.append(f"  Buffered conversations: {len(_cortex_conv_buffer)}")
    except Exception:
        pass

    return "\n".join(lines)


@app.post("/api/chat/arden")
async def chat_arden(payload: dict):
    """Proxy messages directly to the OpenClaw gateway (Arden's brain)."""
    import urllib.request as _ureq

    messages = payload.get("messages", [])
    if not messages:
        raise HTTPException(400, "messages array is required")

    # Inject live dashboard context so Arden can see the dashboard state
    dashboard_ctx = _build_dashboard_context()
    ctx_msg = {
        "role": "system",
        "content": (
            "You have access to the user's Command Center dashboard. "
            "Below is a live snapshot of what is currently visible. "
            "Use this data to answer questions about tasks, budget, "
            "system health, agents, and anything else on the dashboard.\n\n"
            + dashboard_ctx
        ),
    }
    messages_with_ctx = [ctx_msg] + messages

    # Read port + token from openclaw.json
    try:
        with open(OPENCLAW_JSON) as f:
            cfg = json.load(f)
        gw = cfg.get("gateway", {})
        port  = gw.get("port", 18789)
        token = gw.get("auth", {}).get("token", "")
    except Exception:
        port  = 18789
        token = ""

    req_body = json.dumps({
        "model": "auto",
        "messages": messages_with_ctx,
        "max_tokens": 2048,
        "stream": False,
    }).encode("utf-8")

    req = _ureq.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=req_body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        method="POST",
    )

    try:
        with _ureq.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read())
        reply      = (result.get("choices") or [{}])[0].get("message", {}).get("content", "")
        usage      = result.get("usage", {})
        tokens_in  = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        model      = result.get("model", "arden")
        # Log the call so it shows up in routing stats
        call = db.add_routing_call(
            provider="arden",
            model_name=model,
            agent_name="arden-direct",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
        )
        await manager.broadcast("routing_call", call)

        # ── Buffer conversation for Cortex memory ingest ──────────
        # Strip system messages (dashboard context), keep user + assistant only
        user_msgs = [m for m in messages if m.get("role") in ("user", "assistant")]
        if reply and user_msgs:
            user_msgs.append({"role": "assistant", "content": reply})
            _cortex_conv_buffer.append({
                "timestamp": datetime.utcnow().isoformat(),
                "messages": user_msgs,
            })

        return {"reply": reply, "model": model,
                "tokens_in": tokens_in, "tokens_out": tokens_out}
    except Exception as e:
        logger.error(f"Arden gateway error: {e}")
        raise HTTPException(502, f"Gateway error: {str(e)[:120]}")


# ── API: Chat Sessions ─────────────────────────────────────────────────────────
@app.get("/api/sessions")
async def get_sessions():
    return db.get_chat_sessions()

@app.post("/api/sessions")
async def save_session(payload: dict):
    session = db.save_chat_session(
        panel=payload.get("panel", "arden"),
        messages_json=json.dumps(payload.get("messages", [])),
        first_message=payload.get("first_message", ""),
        message_count=payload.get("message_count", 0),
    )
    return session

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: int):
    db.delete_chat_session(session_id)
    return {"status": "deleted"}

@app.delete("/api/sessions")
async def clear_sessions():
    db.clear_chat_sessions()
    return {"status": "cleared"}


# ── API: Command ───────────────────────────────────────────────────────────────
@app.post("/api/command")
async def execute_command(request: Request, payload: dict):
    _rate_check(f"cmd:{request.client.host}", max_per_min=20)
    cmd = payload.get("command", "").strip()
    if not cmd:
        raise HTTPException(400, "command is required")

    parts = cmd.split()
    verb  = parts[0].lower() if parts else ""
    output = ""

    if verb == "trigger" and len(parts) >= 2:
        try:
            await trigger_cron(parts[1])
            output = f"Triggered cron job: {parts[1]}"
        except HTTPException as e:
            output = f"Error: {e.detail}"

    elif verb == "restart" and len(parts) >= 2:
        agent_name = parts[1]
        db.upsert_agent(agent_name, status="idle", last_action="Restarted by operator")
        await manager.broadcast("agent_update", db.get_agents())
        output = f"Agent restarted: {agent_name}"

    elif verb == "run" and len(parts) >= 2:
        agent_name = parts[1]
        prompt = " ".join(parts[2:]) if len(parts) > 2 else "(no prompt)"
        db.upsert_agent(agent_name, status="running", last_action=f"Running: {prompt}")
        log = db.add_log(f"Agent run requested: {agent_name} — {prompt}", "INFO", "system")
        await manager.broadcast("agent_update", db.get_agents())
        await manager.broadcast("new_log", log)
        output = f"Agent '{agent_name}' dispatched: {prompt}"

    elif cmd.lower() == "clear logs":
        db.clear_logs()
        await manager.broadcast("logs_cleared", {})
        db.add_log("Logs cleared by operator", "INFO", "system")
        output = "Logs cleared"

    elif cmd.lower() == "reload avatars":
        state = avatar_manager.reload()
        await manager.broadcast("avatar_update", state)
        output = f"Avatars reloaded — {len(state['all_images'])} images found"

    elif verb == "set" and len(parts) >= 3 and parts[1].lower() == "budget":
        try:
            amount = float(parts[2])
            db.set_budget_limit(amount)
            budget = db.get_budget_summary()
            await manager.broadcast("budget_update", budget)
            output = f"Monthly budget set to ${amount:.2f}"
        except ValueError:
            output = f"Invalid budget amount: {parts[2]}"

    else:
        output = f"Unknown command: {cmd}"

    log = db.add_log(f"Command executed: {cmd} → {output}", "INFO", "system")
    await manager.broadcast("new_log", log)
    return {"command": cmd, "output": output}


# ── Entry Point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HOST, port=PORT,
        reload=False,
        log_level=LOG_LEVEL.lower(),
        ws_ping_interval=20,
        ws_ping_timeout=10,
    )
