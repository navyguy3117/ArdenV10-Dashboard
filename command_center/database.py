"""
database.py - SQLite schema and CRUD operations for Command Center
All tables: agents, logs, routing_calls, budget, cron_jobs, notes, uploads
"""
import sqlite3
import json
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
import threading
import logging

logger = logging.getLogger("command_center.db")


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        # self._seed_mock_data()  # disabled — was seeding fake data into live DB

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            c = conn.cursor()

            c.executescript("""
                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    display_name TEXT,
                    status TEXT DEFAULT 'idle',
                    last_action TEXT,
                    last_active TIMESTAMP,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    agent_name TEXT DEFAULT 'system',
                    level TEXT DEFAULT 'INFO',
                    message TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_logs_agent ON logs(agent_name);
                CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);

                CREATE TABLE IF NOT EXISTS routing_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    provider TEXT NOT NULL,
                    model_name TEXT,
                    actual_model TEXT,
                    agent_name TEXT DEFAULT 'unknown',
                    tokens_in INTEGER DEFAULT 0,
                    tokens_out INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    latency_ms INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_routing_ts ON routing_calls(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_routing_provider ON routing_calls(provider);

                CREATE TABLE IF NOT EXISTS budget (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    period_start DATE NOT NULL,
                    provider TEXT NOT NULL,
                    total_spent REAL DEFAULT 0.0,
                    UNIQUE(period_start, provider)
                );

                CREATE TABLE IF NOT EXISTS budget_config (
                    id INTEGER PRIMARY KEY,
                    monthly_limit REAL DEFAULT 60.0,
                    daily_limit REAL DEFAULT 5.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                INSERT OR IGNORE INTO budget_config (id, monthly_limit, daily_limit) VALUES (1, 60.0, 5.0);

                CREATE TABLE IF NOT EXISTS cron_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    schedule TEXT NOT NULL,
                    description TEXT,
                    last_run TIMESTAMP,
                    next_run TIMESTAMP,
                    last_status TEXT DEFAULT 'PENDING',
                    run_count INTEGER DEFAULT 0,
                    last_output TEXT,
                    command TEXT,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY,
                    content TEXT DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                INSERT OR IGNORE INTO notes (id, content) VALUES (1, '');

                CREATE TABLE IF NOT EXISTS uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    size INTEGER DEFAULT 0,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    path TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS provider_balances (
                    provider TEXT PRIMARY KEY,
                    balance  REAL    DEFAULT 0.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    panel TEXT DEFAULT 'arden',
                    messages_json TEXT DEFAULT '[]',
                    first_message TEXT DEFAULT '',
                    message_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_ts ON chat_sessions(created_at DESC);
            """)
            conn.commit()
            conn.close()

    def _seed_mock_data(self):
        """Populate with realistic mock data for UI verification."""
        with self._lock:
            conn = self._get_conn()
            c = conn.cursor()

            # Only seed if tables are empty
            count = c.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            if count > 0:
                conn.close()
                return

            now = datetime.utcnow()
            today = date.today()

            # Seed agents
            agents = [
                ("claude_agent", "Claude // Reasoning", "running",
                 "Processing user query with extended context window", now.isoformat()),
                ("gpt_router", "GPT // Router", "idle",
                 "Routing complete — 3 tasks delegated", (now - timedelta(minutes=4)).isoformat()),
                ("task_planner", "TaskPlanner // Scheduler", "idle",
                 "Daily plan generated and distributed", (now - timedelta(minutes=12)).isoformat()),
                ("file_manager", "FileOps // Manager", "error",
                 "ERROR: Permission denied on /tmp/agent_cache", (now - timedelta(minutes=1)).isoformat()),
                ("web_searcher", "WebSearch // Crawler", "idle",
                 "Search completed: 14 results indexed", (now - timedelta(hours=2)).isoformat()),
                ("telegram_bot", "Telegram // Gateway", "running",
                 "Listening for incoming messages", now.isoformat()),
                ("memory_agent", "Memory // Archivist", "idle",
                 "Memory consolidation complete: 847 entries", (now - timedelta(minutes=30)).isoformat()),
            ]
            c.executemany(
                "INSERT OR IGNORE INTO agents (name, display_name, status, last_action, last_active) VALUES (?,?,?,?,?)",
                agents
            )

            # Seed logs
            log_data = [
                ("system", "INFO", "Command Center initialized — all systems nominal"),
                ("claude_agent", "INFO", "Model loaded: claude-sonnet-4-6 (128k context)"),
                ("claude_agent", "SUCCESS", "Query processed in 1.24s — 3,847 tokens"),
                ("gpt_router", "INFO", "Routing table updated — 5 active routes"),
                ("task_planner", "WARN", "Task queue depth: 14 items (threshold: 10)"),
                ("file_manager", "ERROR", "Permission denied: /tmp/agent_cache/session_8f2a"),
                ("system", "INFO", "Budget check: $45.20 of $60.00 used this month"),
                ("web_searcher", "INFO", "Search index updated: 14 new documents"),
                ("telegram_bot", "INFO", "Telegram webhook connected — polling active"),
                ("memory_agent", "SUCCESS", "Memory consolidation complete: 847 entries archived"),
                ("claude_agent", "DEBUG", "Context window: 12,450 / 128,000 tokens"),
                ("system", "WARN", "CPU spike detected: 78% on core 3"),
                ("gpt_router", "INFO", "OpenRouter model auto-selected: llama-3.1-70b"),
                ("claude_agent", "SUCCESS", "Tool call completed: web_search() → 12 results"),
                ("system", "INFO", "WebSocket clients connected: 2"),
                ("file_manager", "INFO", "File watcher started on /workspace/imports"),
                ("task_planner", "INFO", "Cron job triggered: daily_summary"),
                ("memory_agent", "DEBUG", "Embedding generated for 47 new memories"),
                ("system", "SUCCESS", "Health check passed — all services responding"),
                ("claude_agent", "INFO", "Starting multi-step reasoning task: 4 subtasks"),
                ("web_searcher", "WARN", "Rate limit approaching: 85/100 requests used"),
                ("gpt_router", "INFO", "Fallback to Anthropic: OpenAI latency >5s"),
                ("system", "INFO", "Quick launch config reloaded — 6 buttons"),
                ("telegram_bot", "SUCCESS", "Message delivered to user — 142ms latency"),
                ("file_manager", "SUCCESS", "File uploaded: report_q4_2025.pdf (2.4MB)"),
                ("claude_agent", "WARN", "Token budget 70% used in current session"),
                ("system", "DEBUG", "Metrics broadcast: CPU 45%, RAM 62%"),
                ("task_planner", "INFO", "Next scheduled task: health_check in 8 minutes"),
                ("gpt_router", "ERROR", "OpenAI API timeout after 10s — retrying"),
                ("system", "SUCCESS", "All systems green — Arden at full capacity"),
            ]
            ts_base = now - timedelta(minutes=len(log_data))
            for i, (agent, level, msg) in enumerate(log_data):
                ts = (ts_base + timedelta(minutes=i)).isoformat()
                c.execute(
                    "INSERT INTO logs (timestamp, agent_name, level, message) VALUES (?,?,?,?)",
                    (ts, agent, level, msg)
                )

            # Seed routing calls
            providers_models = [
                ("anthropic", "claude-sonnet-4-6", "claude-sonnet-4-6", 2450, 387, 0.0187),
                ("openai", "gpt-4o", "gpt-4o", 1820, 241, 0.0142),
                ("openrouter", "openrouter/auto", "meta-llama/llama-3.1-70b-instruct", 890, 156, 0.0008),
                ("anthropic", "claude-opus-4-6", "claude-opus-4-6", 5200, 612, 0.0891),
                ("openai", "gpt-4o-mini", "gpt-4o-mini", 634, 98, 0.0003),
                ("openrouter", "openrouter/auto", "anthropic/claude-3.5-sonnet", 1340, 298, 0.0065),
                ("local", "lmstudio/local", "llama-3.2-3b-instruct", 445, 89, 0.0),
                ("anthropic", "claude-sonnet-4-6", "claude-sonnet-4-6", 3890, 445, 0.0298),
                ("openai", "gpt-4o", "gpt-4o", 2100, 312, 0.0187),
                ("openrouter", "openrouter/auto", "google/gemma-2-27b-it", 710, 134, 0.0004),
                ("anthropic", "claude-haiku-4-5", "claude-haiku-4-5-20251001", 890, 145, 0.0012),
                ("openai", "gpt-4o-mini", "gpt-4o-mini", 523, 87, 0.0002),
                ("local", "lmstudio/local", "qwen2.5-coder-7b", 1230, 234, 0.0),
                ("anthropic", "claude-sonnet-4-6", "claude-sonnet-4-6", 4560, 534, 0.0345),
                ("openrouter", "openrouter/auto", "mistralai/mistral-large", 1890, 267, 0.0032),
            ]
            agents_list = ["claude_agent", "gpt_router", "task_planner", "web_searcher", "memory_agent"]
            for i, (prov, model, actual, tin, tout, cost) in enumerate(providers_models):
                ts = (now - timedelta(minutes=(len(providers_models) - i) * 3)).isoformat()
                agent = agents_list[i % len(agents_list)]
                latency = 450 + (i * 127) % 3500
                c.execute(
                    "INSERT INTO routing_calls (timestamp, provider, model_name, actual_model, agent_name, tokens_in, tokens_out, cost_usd, latency_ms) VALUES (?,?,?,?,?,?,?,?,?)",
                    (ts, prov, model, actual, agent, tin, tout, cost, latency)
                )

            # Seed budget
            period_start = today.replace(day=1).isoformat()
            for provider, spent in [("anthropic", 22.45), ("openai", 14.32), ("openrouter", 8.43)]:
                c.execute(
                    "INSERT OR IGNORE INTO budget (period_start, provider, total_spent) VALUES (?,?,?)",
                    (period_start, provider, spent)
                )

            # Seed cron jobs
            cron_jobs = [
                ("daily_summary", "0 8 * * *", "Generate daily activity summary",
                 (now - timedelta(hours=16)).isoformat(), (now + timedelta(hours=8)).isoformat(),
                 "SUCCESS", 47, "Summary generated: 23 tasks completed, 4 pending", "python scripts/daily_summary.py"),
                ("health_check", "*/10 * * * *", "System health verification",
                 (now - timedelta(minutes=4)).isoformat(), (now + timedelta(minutes=6)).isoformat(),
                 "SUCCESS", 2847, "All 7 services healthy. CPU: 45%, RAM: 62%", "bash scripts/health_check.sh"),
                ("cache_cleanup", "0 */4 * * *", "Clear expired agent cache files",
                 (now - timedelta(hours=3)).isoformat(), (now + timedelta(hours=1)).isoformat(),
                 "SUCCESS", 312, "Cleaned 847MB from /tmp/agent_cache", "python scripts/cache_cleanup.py"),
                ("memory_consolidate", "0 2 * * *", "Consolidate and archive agent memories",
                 (now - timedelta(hours=22)).isoformat(), (now + timedelta(hours=2)).isoformat(),
                 "SUCCESS", 31, "Archived 847 memories, freed 1.2GB", "python scripts/memory_consolidate.py"),
                ("budget_report", "0 0 * * 1", "Weekly budget and usage report",
                 (now - timedelta(days=3)).isoformat(), (now + timedelta(days=4)).isoformat(),
                 "PENDING", 12, None, "python scripts/budget_report.py"),
            ]
            c.executemany(
                "INSERT OR IGNORE INTO cron_jobs (name, schedule, description, last_run, next_run, last_status, run_count, last_output, command) VALUES (?,?,?,?,?,?,?,?,?)",
                cron_jobs
            )

            # Seed notes
            c.execute(
                "UPDATE notes SET content=? WHERE id=1",
                ("# Arden Command Center Notes\n\n## Active Tasks\n- [ ] Review budget overage on Anthropic API\n- [ ] Update web_searcher rate limits\n- [ ] Deploy new memory_agent v2.1\n\n## Ideas\n- Add Redis caching layer for frequent queries\n- Implement streaming responses for long tasks\n\n## Reminders\n- Monthly budget resets on the 1st\n- Telegram bot token expires 2026-03-15",)
            )

            # Seed uploads
            upload_data = [
                ("report_q4_2025.pdf", "report_q4_2025.pdf", 2457600,
                 (now - timedelta(hours=2)).isoformat(), "/workspace/imports/uploaded-docs/report_q4_2025.pdf"),
                ("agent_config_backup.json", "agent_config_backup.json", 45312,
                 (now - timedelta(hours=5)).isoformat(), "/workspace/imports/uploaded-docs/agent_config_backup.json"),
                ("training_data_batch3.csv", "training_data_batch3.csv", 8912384,
                 (now - timedelta(days=1)).isoformat(), "/workspace/imports/uploaded-docs/training_data_batch3.csv"),
            ]
            c.executemany(
                "INSERT OR IGNORE INTO uploads (filename, original_name, size, timestamp, path) VALUES (?,?,?,?,?)",
                upload_data
            )

            conn.commit()
            conn.close()
            logger.info("Mock data seeded successfully")

    # ── AGENTS ──────────────────────────────────────────────────────────────
    def get_agents(self) -> List[Dict]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT * FROM agents ORDER BY last_active DESC").fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def upsert_agent(self, name: str, display_name: str = None, status: str = "idle",
                     last_action: str = None, metadata: dict = None) -> Dict:
        with self._lock:
            conn = self._get_conn()
            now = datetime.utcnow().isoformat()
            conn.execute("""
                INSERT INTO agents (name, display_name, status, last_action, last_active, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    display_name = COALESCE(excluded.display_name, display_name),
                    status = excluded.status,
                    last_action = COALESCE(excluded.last_action, last_action),
                    last_active = excluded.last_active,
                    metadata = COALESCE(excluded.metadata, metadata)
            """, (name, display_name, status, last_action, now, json.dumps(metadata or {})))
            conn.commit()
            row = conn.execute("SELECT * FROM agents WHERE name=?", (name,)).fetchone()
            conn.close()
            return dict(row)

    def get_agent_logs(self, agent_name: str, limit: int = 20) -> List[Dict]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM logs WHERE agent_name=? ORDER BY timestamp DESC LIMIT ?",
                (agent_name, limit)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    # ── LOGS ─────────────────────────────────────────────────────────────────
    def add_log(self, message: str, level: str = "INFO", agent_name: str = "system") -> Dict:
        with self._lock:
            conn = self._get_conn()
            now = datetime.utcnow().isoformat()
            cur = conn.execute(
                "INSERT INTO logs (timestamp, agent_name, level, message) VALUES (?,?,?,?)",
                (now, agent_name, level.upper(), message)
            )
            conn.commit()
            row = conn.execute("SELECT * FROM logs WHERE id=?", (cur.lastrowid,)).fetchone()
            conn.close()
            return dict(row)

    def get_logs(self, limit: int = 200, level: str = None, agent_name: str = None) -> List[Dict]:
        with self._lock:
            conn = self._get_conn()
            query = "SELECT * FROM logs WHERE 1=1"
            params = []
            if level:
                query += " AND level=?"
                params.append(level.upper())
            if agent_name:
                query += " AND agent_name=?"
                params.append(agent_name)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def clear_logs(self):
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM logs")
            conn.commit()
            conn.close()

    # ── ROUTING CALLS ────────────────────────────────────────────────────────
    def add_routing_call(self, provider: str, model_name: str, agent_name: str = "unknown",
                         tokens_in: int = 0, tokens_out: int = 0, cost_usd: float = 0.0,
                         latency_ms: int = 0, actual_model: str = None) -> Dict:
        with self._lock:
            conn = self._get_conn()
            now = datetime.utcnow().isoformat()
            cur = conn.execute("""
                INSERT INTO routing_calls (timestamp, provider, model_name, actual_model, agent_name, tokens_in, tokens_out, cost_usd, latency_ms)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (now, provider, model_name, actual_model or model_name, agent_name,
                  tokens_in, tokens_out, cost_usd, latency_ms))
            # Update budget
            period_start = date.today().replace(day=1).isoformat()
            conn.execute("""
                INSERT INTO budget (period_start, provider, total_spent)
                VALUES (?,?,?)
                ON CONFLICT(period_start, provider) DO UPDATE SET
                    total_spent = total_spent + excluded.total_spent
            """, (period_start, provider, cost_usd))
            conn.commit()
            row = conn.execute("SELECT * FROM routing_calls WHERE id=?", (cur.lastrowid,)).fetchone()
            conn.close()
            return dict(row)

    def get_routing_calls(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM routing_calls ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def get_provider_spend_since(self, provider: str, since: "datetime") -> float:
        """Sum cost_usd for non-external routing_calls for a provider since given datetime.
        Excludes synthetic ⚡ EXTERNAL entries to avoid double-counting."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                """SELECT COALESCE(SUM(cost_usd), 0) as total
                   FROM routing_calls
                   WHERE provider = ? AND timestamp >= ? AND agent_name != '⚡ EXTERNAL'""",
                (provider, since.isoformat())
            ).fetchone()
            conn.close()
            return float(row["total"])

    def get_routing_stats(self) -> Dict:
        with self._lock:
            conn = self._get_conn()
            today = datetime.utcnow().date().isoformat()
            hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
            # Daily stats
            rows = conn.execute("""
                SELECT provider,
                       COUNT(*) as calls_today,
                       SUM(tokens_in + tokens_out) as tokens_today,
                       SUM(cost_usd) as cost_today,
                       MAX(timestamp) as last_call,
                       AVG(CASE WHEN latency_ms > 0 THEN latency_ms END) as avg_latency,
                       SUM(CASE WHEN cost_usd = 0 AND tokens_out = 0 THEN 1 ELSE 0 END) as zero_output_count
                FROM routing_calls
                WHERE date(timestamp) = ?
                GROUP BY provider
            """, (today,)).fetchall()
            # 1-hour counts
            hour_rows = conn.execute("""
                SELECT provider, COUNT(*) as calls_1h
                FROM routing_calls
                WHERE timestamp >= ?
                GROUP BY provider
            """, (hour_ago,)).fetchall()
            hour_map = {r["provider"]: r["calls_1h"] for r in hour_rows}
            conn.close()
            result = {}
            for r in rows:
                d = dict(r)
                prov = d["provider"]
                total = d["calls_today"] or 0
                zero = d.get("zero_output_count") or 0
                d["error_rate"] = round(zero / total, 3) if total > 0 else None
                d["calls_1h"] = hour_map.get(prov, 0)
                d["avg_latency"] = round(d["avg_latency"], 0) if d["avg_latency"] else None
                result[prov] = d
            return result

    # ── BUDGET ───────────────────────────────────────────────────────────────
    def get_budget_summary(self) -> Dict:
        with self._lock:
            conn = self._get_conn()
            period_start = date.today().replace(day=1).isoformat()
            config = conn.execute("SELECT * FROM budget_config WHERE id=1").fetchone()
            rows = conn.execute(
                "SELECT * FROM budget WHERE period_start=?", (period_start,)
            ).fetchall()

            total_spent = sum(r["total_spent"] for r in rows)
            monthly_limit = config["monthly_limit"] if config else 60.0
            daily_limit = config["daily_limit"] if config else 5.0

            # Daily spent
            today = datetime.utcnow().date().isoformat()
            daily_row = conn.execute(
                "SELECT SUM(cost_usd) as daily FROM routing_calls WHERE date(timestamp)=?",
                (today,)
            ).fetchone()
            daily_spent = daily_row["daily"] or 0.0

            # Days elapsed in period
            days_elapsed = max(1, date.today().day)
            days_in_month = 30
            burn_rate = total_spent / days_elapsed
            projected = burn_rate * days_in_month

            conn.close()
            return {
                "monthly_limit": monthly_limit,
                "daily_limit": daily_limit,
                "total_spent": round(total_spent, 4),
                "remaining": round(max(0, monthly_limit - total_spent), 4),
                "daily_spent": round(daily_spent, 4),
                "daily_burn_rate": round(burn_rate, 4),
                "projected_month_end": round(projected, 4),
                "percent_used": round((total_spent / monthly_limit) * 100, 1) if monthly_limit > 0 else 0,
                "by_provider": {r["provider"]: round(r["total_spent"], 4) for r in rows},
                "period_start": period_start,
            }

    def set_budget_limit(self, monthly_limit: float, daily_limit: float = None):
        with self._lock:
            conn = self._get_conn()
            now = datetime.utcnow().isoformat()
            if daily_limit is not None:
                conn.execute(
                    "UPDATE budget_config SET monthly_limit=?, daily_limit=?, updated_at=? WHERE id=1",
                    (monthly_limit, daily_limit, now)
                )
            else:
                conn.execute(
                    "UPDATE budget_config SET monthly_limit=?, updated_at=? WHERE id=1",
                    (monthly_limit, now)
                )
            conn.commit()
            conn.close()

    # ── PROVIDER BUCKET BALANCES ─────────────────────────────────────────────
    def get_provider_balances(self) -> Dict:
        """Return {provider: {balance, updated_at}} for manual reconciliation."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT provider, balance, updated_at FROM provider_balances"
            ).fetchall()
            conn.close()
            return {r["provider"]: {"balance": r["balance"], "updated_at": r["updated_at"]}
                    for r in rows}

    def set_provider_balance(self, provider: str, balance: float) -> None:
        """Upsert the manually-set bucket balance for a provider."""
        with self._lock:
            conn = self._get_conn()
            now = datetime.utcnow().isoformat()
            conn.execute(
                """INSERT INTO provider_balances (provider, balance, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(provider) DO UPDATE SET
                       balance    = excluded.balance,
                       updated_at = excluded.updated_at""",
                (provider, balance, now)
            )
            conn.commit()
            conn.close()

    # ── LOCAL LM SAVINGS ─────────────────────────────────────────────────────
    def get_savings_summary(self, cloud_in_rate: float = 1.0, cloud_out_rate: float = 3.0) -> dict:
        """Estimate savings from local LM vs equivalent cloud cost.
        Default comparison rate: $1.00 in / $3.00 out per 1M tokens (mid-tier cloud).
        """
        with self._lock:
            conn = self._get_conn()
            period_start = date.today().replace(day=1).isoformat()

            mtd = conn.execute("""
                SELECT COUNT(*) as calls,
                       COALESCE(SUM(tokens_in),0)  as tin,
                       COALESCE(SUM(tokens_out),0) as tout
                FROM routing_calls
                WHERE provider IN ('local','lmstudio','ollama') AND date(timestamp) >= ?
            """, (period_start,)).fetchone()

            all_time = conn.execute("""
                SELECT COUNT(*) as calls,
                       COALESCE(SUM(tokens_in),0)  as tin,
                       COALESCE(SUM(tokens_out),0) as tout
                FROM routing_calls
                WHERE provider IN ('local','lmstudio','ollama')
            """).fetchone()

            conn.close()

            def _calc(row):
                tin  = row["tin"]  or 0
                tout = row["tout"] or 0
                est  = round((tin * cloud_in_rate + tout * cloud_out_rate) / 1_000_000, 4)
                return {"calls": row["calls"] or 0, "tokens_in": tin, "tokens_out": tout,
                        "tokens_total": tin + tout, "actual_cost": 0.0,
                        "estimated_cloud_cost": est, "saved": est}

            return {
                "mtd":      _calc(mtd),
                "all_time": _calc(all_time),
                "cloud_rate": {"in_per_1m": cloud_in_rate, "out_per_1m": cloud_out_rate},
            }

    # ── CRON JOBS ────────────────────────────────────────────────────────────
    def get_cron_jobs(self) -> List[Dict]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute("SELECT * FROM cron_jobs ORDER BY name").fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def upsert_cron_job(self, name: str, schedule: str, description: str = None,
                        command: str = None) -> Dict:
        with self._lock:
            conn = self._get_conn()
            now = datetime.utcnow().isoformat()
            conn.execute("""
                INSERT INTO cron_jobs (name, schedule, description, command)
                VALUES (?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                    schedule = excluded.schedule,
                    description = COALESCE(excluded.description, description),
                    command = COALESCE(excluded.command, command)
            """, (name, schedule, description, command))
            conn.commit()
            row = conn.execute("SELECT * FROM cron_jobs WHERE name=?", (name,)).fetchone()
            conn.close()
            return dict(row)

    def update_cron_run(self, name: str, status: str, output: str = None):
        with self._lock:
            conn = self._get_conn()
            now = datetime.utcnow().isoformat()
            conn.execute("""
                UPDATE cron_jobs SET
                    last_run = ?,
                    last_status = ?,
                    run_count = run_count + 1,
                    last_output = COALESCE(?, last_output)
                WHERE name = ?
            """, (now, status.upper(), output, name))
            conn.commit()
            conn.close()

    # ── NOTES ────────────────────────────────────────────────────────────────
    def get_notes(self) -> str:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT content FROM notes WHERE id=1").fetchone()
            conn.close()
            return row["content"] if row else ""

    def save_notes(self, content: str):
        with self._lock:
            conn = self._get_conn()
            now = datetime.utcnow().isoformat()
            conn.execute("UPDATE notes SET content=?, updated_at=? WHERE id=1", (content, now))
            conn.commit()
            conn.close()

    # ── UPLOADS ──────────────────────────────────────────────────────────────
    def add_upload(self, filename: str, original_name: str, size: int, path: str) -> Dict:
        with self._lock:
            conn = self._get_conn()
            now = datetime.utcnow().isoformat()
            cur = conn.execute(
                "INSERT INTO uploads (filename, original_name, size, timestamp, path) VALUES (?,?,?,?,?)",
                (filename, original_name, size, now, path)
            )
            conn.commit()
            row = conn.execute("SELECT * FROM uploads WHERE id=?", (cur.lastrowid,)).fetchone()
            conn.close()
            return dict(row)

    def get_uploads(self, limit: int = 10) -> List[Dict]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM uploads ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    # ── CHAT SESSIONS ────────────────────────────────────────────────────────
    def get_chat_sessions(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM chat_sessions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def save_chat_session(self, panel: str, messages_json: str,
                          first_message: str = '', message_count: int = 0) -> Dict:
        with self._lock:
            conn = self._get_conn()
            now = datetime.utcnow().isoformat()
            cur = conn.execute(
                "INSERT INTO chat_sessions (panel, messages_json, first_message, message_count, created_at) VALUES (?,?,?,?,?)",
                (panel, messages_json, first_message, message_count, now)
            )
            conn.commit()
            row = conn.execute("SELECT * FROM chat_sessions WHERE id=?", (cur.lastrowid,)).fetchone()
            conn.close()
            return dict(row)

    def delete_chat_session(self, session_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
            conn.commit()
            conn.close()

    def clear_chat_sessions(self):
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM chat_sessions")
            conn.commit()
            conn.close()

    # ── LAST ACTIVITY ────────────────────────────────────────────────────────
    def get_last_activity(self) -> Optional[Dict]:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM logs ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            conn.close()
            return dict(row) if row else None
