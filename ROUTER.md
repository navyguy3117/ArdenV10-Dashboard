# ROUTER.md – Local LLM Router

This document describes the local "LLM Router" service that runs **inside** your OpenClaw workspace.

- Safe workspace only: everything lives under `/home/mikegg/.openclaw/workspace`.
- No `sudo`, no access outside this workspace.
- API keys are **only** read from environment variables, never logged or written to disk.

## 1. Architecture overview

### 1.1. High-level

The router is a small HTTP service (Python + FastAPI) exposing:

- `GET /health`
  - Returns basic status: `ok`, provider budget snapshots, and a simple uptime indicator.
- `POST /v1/chat/completions`
  - **OpenAI-compatible** endpoint that accepts chat-style requests and returns responses shaped like OpenAI's `chat.completion` objects.

Internally the router has these layers:

1. **Request handler (FastAPI)**
   - Parses the incoming request body (OpenAI-style: `model`, `messages`, `max_tokens`, etc.).
   - Reads optional `metadata` for routing hints (intent, priority, route override, model override, verify/second-opinion).

2. **Routing layer** (`routing.py`)
   - Infers **intent**: casual chat, coding/scripting, deep reasoning/planning, vision, verify/second-opinion.
   - Applies **routing policy** (see table below) using:
     - intent
     - priority (`low | normal | high`)
     - requested `max_tokens`
   - Applies **routing overrides** (if present):
     - `metadata.route = "openai" | "anthropic" | "openrouter"`
     - `metadata.model = "<model-id>"`
     - Overrides are honored **unless** they would break budget caps.
   - Produces a `RouteDecision` object: provider, model, tier, reason, forced/not-forced.

3. **Budget manager** (`budget.py`)
   - Tracks **estimated** token usage per provider:
     - daily usage
     - monthly usage
   - Uses a simple approximation: `approx_tokens ≈ char_count / 4`, plus a safety margin.
   - Enforces caps defined in `configs/router.yaml`:
     - `monthly_cap_per_provider` (default `$60`)
     - derived `daily_cap_per_provider` (monthly/30) with optional override.
   - If a chosen provider would exceed its daily or monthly cap:
     - Attempts to downgrade to a cheaper tier for that provider.
     - If still over budget, attempts to route to another provider.
     - If no provider can serve within caps, returns an error.

4. **Context manager / token optimizer** (`context.py`)
   - Applies token budgeting rules **before any provider call**:
     - Calculates approximate input tokens for the message list.
     - Enforces `target_input_tokens` and `hard_max_input_tokens` per priority.
     - Removes obvious noise:
       - repeated banners / boilerplate
       - large tool output dumps unless clearly needed
       - duplicate assistant replies
     - Applies **recency bias**: prefers recent turns, drops the oldest non-pinned messages first.
     - Always preserves:
       - system instructions
       - behavior rules snapshot (from `USER.md`)
       - pinned items from `/memory/pins.md`.
   - If input exceeds `target_input_tokens`:
     - Builds a **rolling summary** of older context:
       - Uses the **cheap summarizer policy** (see section 5).
       - Replaces older messages with a short summary message.
       - Writes a summary entry to `/memory/router-summaries/YYYY-MM-DD.md`.
   - Enforces `hard_max_input_tokens` after summarization by dropping more old, non-pinned content if necessary.

5. **Provider clients** (`providers.py`)
   - Thin wrappers for:
     - OpenAI (`OPENAI_API_KEY`)
     - Anthropic (`ANTHROPIC_API_KEY`)
     - OpenRouter (`OPENROUTER_API_KEY`)
   - Each client:
     - Accepts a normalized internal request (messages, model, max_tokens, temperature, etc.).
     - Calls the provider's API.
     - Returns an **OpenAI-compatible** response payload:
       - `id`, `object`, `created`, `model`, `choices`, `usage`.

6. **Logging layer** (`logging_utils.py`)
   - Logs:
     - Requests (without content) to `logs/router-requests.log`.
     - Errors and fallback chains to `logs/router-errors.log`.
     - Context trimming stats to `logs/router-context.log`.

7. **Fallback controller**
   - Handles retries and provider fallback:
     - Up to **2 retries per provider** on transient errors.
     - Then fails over to the next provider in the fallback chain, as specified in `router.yaml`.

All code lives under:

- `/home/mikegg/.openclaw/workspace/router/` (source)
- `/home/mikegg/.openclaw/workspace/configs/router.yaml` (config)
- `/home/mikegg/.openclaw/workspace/logs/` (logs)
- `/home/mikegg/.openclaw/workspace/memory/` (router summaries + pins)


## 2. Routing policy

### 2.1. Intents

The router works with these primary intents:

- `chat` – casual conversation, lightweight Q&A
- `code` – coding, scripting, debugging, error analysis
- `reasoning` – deep reasoning, complex planning, multi-step analysis
- `vision` – image + text inputs
- `verify` – second-opinion / cross-check requests

Intent is determined from:

- `metadata.intent` in the request (if present)
- otherwise, heuristics based on the latest user message (keywords, presence of code blocks, presence of images).

### 2.2. Priority & max_tokens

The router also considers:

- `priority`: `low | normal | high` (from `metadata.priority`, default `normal`)
- `max_tokens` from the request (if not set, we use a reasonable default per tier)

These influence:

- choice of provider/model
- how aggressively to trim context
- whether to allow more context (especially for `reasoning` and `high` priority)

### 2.3. Routing table (conceptual)

The actual model IDs come from `configs/router.yaml`. Conceptually:

| Intent    | Priority | Tier used           | Provider preference            |
|----------|----------|---------------------|--------------------------------|
| chat     | low      | CHEAP_CHAT          | OpenRouter → OpenAI fallback  |
| chat     | normal   | CHEAP_CHAT          | OpenRouter → OpenAI           |
| chat     | high     | CHEAP_CHAT          | OpenRouter → OpenAI           |
| code     | low      | CODE_PRIMARY        | OpenAI ↔ Anthropic (cost-based) |
| code     | normal   | CODE_PRIMARY        | OpenAI ↔ Anthropic            |
| code     | high     | CODE_PRIMARY        | OpenAI ↔ Anthropic            |
| reasoning| low      | REASONING_PRIMARY   | Anthropic → OpenAI            |
| reasoning| normal   | REASONING_PRIMARY   | Anthropic → OpenAI            |
| reasoning| high     | REASONING_PRIMARY   | Anthropic → OpenAI            |
| vision   | any      | VISION_PRIMARY      | Provider w/ best vision model |
| verify   | any      | same tier as primary, **different provider** | depends on primary |

Additionally:

- If budget for the preferred provider is near/over cap, router falls back to a cheaper tier or another provider.
- For `verify`, router ensures the provider is **different** from the one that produced the original answer.

### 2.4. Routing overrides

The caller may request explicit routing overrides via `metadata`:

- `metadata.route = "openai" | "anthropic" | "openrouter"`
  - Forces the provider selection, as long as budget caps are not violated.
- `metadata.model = "<model-id>"`
  - Forces an exact model, as long as budget caps are not violated.

If an override is applied:

- The router logs `forced_route: true` with the forced provider/model.

If an override would break the daily or monthly cap:

- The router logs that the override was **rejected** due to budget.
- The router then falls back to the normal routing policy.


## 3. Budget logic

### 3.1. Budget model

- Each provider (OpenAI, Anthropic, OpenRouter) has a **monthly** budget cap, default **$60**.
- A derived **daily** cap is computed as `monthly / 30` (default `$2/day` per provider).
- A `daily_override` per provider can be set in `router.yaml`.

The router uses approximate cost tracking:

1. Estimate tokens in/out per request using `char_count / 4`, with a safety margin.
2. Convert tokens to approximate cost using per-model cost settings from `router.yaml`.
3. Maintain in-memory counters per provider:
   - `estimated_daily_cost` (resets daily)
   - `estimated_monthly_cost`

> Note: this is an approximate safety mechanism, not a billing-grade meter.

### 3.2. Enforcement

Before making a provider call:

1. Estimate cost for the request.
2. If adding this cost would exceed the **daily** or **monthly** cap for that provider:
   - Try a cheaper tier for the same provider (e.g. `FALLBACK_CHEAP`).
   - If still over budget, try another provider according to fallback chain.
3. If **no** provider can serve the request within caps:
   - Return an error in OpenAI-compatible format indicating budget exhaustion.

Overrides:

- If `metadata.route` / `metadata.model` is used, the **same checks apply**.
- Overrides are not allowed to bypass caps.


## 4. Fallback logic

For each request, the router builds a **fallback chain** like:

1. Primary: provider + model tier from routing policy
2. Secondary: same tier on another provider or cheaper tier on same provider
3. Tertiary: `FALLBACK_CHEAP` on any available provider under budget

Retries:

- For each provider in the chain, the router may attempt up to **2 retries** on transient errors (network, 5xx, timeouts).
- After retries are exhausted for that provider, it moves to the next provider in the chain.
- Each attempt and fallback is logged to `logs/router-errors.log`.


## 5. Token optimization & context control

### 5.1. Token budgets

Per request, we enforce:

- `target_input_tokens` – soft target (e.g. 6000 by default)
- `hard_max_input_tokens` – absolute cap (e.g. 10000 by default)

These values are configurable in `router.yaml` and can vary by `priority` (`low`, `normal`, `high`).

### 5.2. Context trimming rules

Before calling a provider, the router:

1. Estimates token usage for the message list.
2. Always keeps:
   - System messages.
   - A snapshot of behavior rules (derived from `USER.md`).
   - All **pinned** items from `/memory/pins.md`.
3. Removes obvious noise:
   - Repeated system banners.
   - Large tool/output dumps unless clearly required.
   - Duplicate assistant messages.
4. Applies **recency bias**:
   - Start trimming from the oldest non-pinned messages.

### 5.3. Cheap summarizer policy

If, after trimming obvious noise, the approximate input tokens exceed `target_input_tokens`:

1. The router builds a **rolling summary** of the older conversation segments.
2. Summarizer behavior:
   - Uses the **cheapest model tier** (`FALLBACK_CHEAP`) by default.
   - If `priority=high`, uses a configurable `summarizer_high_priority_tier` (e.g. `REASONING_PRIMARY`).
   - Requests **no more than 350–500 tokens** for the summary (configurable in `router.yaml`).
3. The older messages are replaced with a single summary message that captures:
   - Key decisions.
   - Key facts.
   - Essential context for the current question.
4. A copy of the summary (without secrets/API keys) is written to:
   - `/memory/router-summaries/YYYY-MM-DD.md`.

If the context is **still** larger than `hard_max_input_tokens`, the router will drop additional oldest, non-pinned pieces until the hard cap is respected.

### 5.4. Pinned memory mechanism

The router supports "pinned" content that should stay in context:

- Any message containing `[PIN] ...` is treated as pinned.
- Pinned items are stored in `/memory/pins.md` with timestamps.
- During context construction, pinned items are always included (as long as they fit under hard caps).
- Future versions can support explicit unpin commands; initial implementation will treat pins as persistent until the file is edited.

### 5.5. Context trimming logging

All trimming decisions are logged to `logs/router-context.log` with:

- timestamp
- `input_tokens_before`
- `input_tokens_after`
- `method` (`drop`, `summarize`, `keep`)
- `pinned_included` (true/false)
- `summarizer_tier_used` (if any)
- `summary_tokens_requested` (if any)

## 5.6 Local Provider Visibility (Mission Control Signal)

The router must expose enough signal for the Command Center dashboard to show
WHERE inference actually happened.

### Goal

Allow the dashboard to clearly show:

- LM Studio (4090) active
- Ollama (2080 laptop) active
- OpenRouter / external provider active

This is observability only — not control logic.

### Required signals

For every request routed, include in logs:

- `execution_target`
  - `lmstudio`
  - `ollama`
  - `openrouter`
  - `openai`
  - `anthropic`

- `execution_host`
  - Example:
    - `10.10.10.98` (LM Studio)
    - `10.10.10.175` (Ollama)
    - `external`

- `execution_mode`
  - `local_gpu`
  - `remote_gpu`
  - `external_api`

### Health checks (read-only)

Router may perform lightweight checks:

- LM Studio:
  - `GET http://10.10.10.98:1234/v1/models`
- Ollama:
  - `GET http://10.10.10.175:11434/api/tags`

These checks:

- MUST be read-only
- MUST NOT trigger inference
- Used only for dashboard status indicators

### Dashboard usage

Command Center should display:

- Current active execution target
- Last N routing executions
- Local vs external usage ratio

Example display:



## 6. Logging & observability

### 6.1. Request logs – `logs/router-requests.log`

Each request produces a single log entry including:

- timestamp
- provider
- model
- tier
- intent
- priority
- `forced_route` (bool)
- `forced_provider` / `forced_model` when applicable
- estimated_tokens_in
- estimated_tokens_out (if available)
- short reason string for route choice

**No** request content is logged by default (no prompts, no messages).

### 6.2. Error logs – `logs/router-errors.log`

On errors, log:

- timestamp
- provider + model
- error type / message
- which fallback attempt this was (primary/secondary/tertiary, attempt number)
- sanitized stack trace

### 6.3. Context logs – `logs/router-context.log`

As described in section 5.5, for trimming and summarization details.


## 7. Filesystem layout

Within `/home/mikegg/.openclaw/workspace`:

- `router/`
  - `main.py` – FastAPI app, endpoints
  - `config.py` – config loader for `router.yaml`
  - `routing.py` – intent detection, route selection, fallback chains
  - `providers.py` – clients for OpenAI, Anthropic, OpenRouter
  - `context.py` – token estimation, trimming, summarization, pins integration
  - `budget.py` – budget tracking & enforcement
  - `logging_utils.py` – helpers for structured logging
- `configs/`
  - `router.yaml` – all routing, budget, model tier, and token rules
  - `openclaw-router.service` – optional `systemd --user` unit for WSL (no keys inside)
- `logs/`
  - `router-requests.log`
  - `router-errors.log`
  - `router-context.log`
- `memory/`
  - `router-summaries/` – daily rolling summaries
  - `pins.md` – pinned items


## 8. How to run

From inside `/home/mikegg/.openclaw/workspace` after installing dependencies (`fastapi`, `uvicorn`, and provider SDKs if desired):

```bash
# Example (no sudo)
uvicorn router.main:app --host 0.0.0.0 --port 8001
```

Or via the optional `systemd --user` service file (you would enable this yourself). The service file will use this workspace as its `WorkingDirectory`.


## 9. How to test

Assuming the router is running on `http://localhost:8001`.

### 9.1. Health check

```bash
curl http://localhost:8001/health
```

Expected output (example):

```json
{
  "status": "ok",
  "providers": {
    "openai": {"daily_cost_estimate": 0.12, "monthly_cost_estimate": 3.4},
    "anthropic": {"daily_cost_estimate": 0.00, "monthly_cost_estimate": 0.0},
    "openrouter": {"daily_cost_estimate": 0.01, "monthly_cost_estimate": 0.3}
  }
}
```

### 9.2. Simple chat completion

```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "auto",
    "messages": [
      {"role": "user", "content": "Hello, who are you?"}
    ]
  }'
```

Expected (shape, not exact content):

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "<actual-model-used>",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 20,
    "completion_tokens": 30,
    "total_tokens": 50
  }
}
```

### 9.3. Coding request

```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "auto",
    "messages": [
      {"role": "user", "content": "Write a Python function that reverses a string."}
    ],
    "metadata": {"intent": "code", "priority": "normal"}
  }'
```

Expected: routed to `CODE_PRIMARY` tier and provider chosen in `router.yaml` (OpenAI/Anthropic), returning code-like output.

### 9.4. Deep reasoning request

```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "auto",
    "messages": [
      {"role": "user", "content": "Help me plan a migration from server A to server B with minimal downtime."}
    ],
    "metadata": {"intent": "reasoning", "priority": "high"}
  }'
```

Expected: routed to `REASONING_PRIMARY` tier (Anthropic preferred), with more allowed context.

### 9.5. Forced routing

```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "auto",
    "messages": [
      {"role": "user", "content": "Short answer: what is 2+2?"}
    ],
    "metadata": {"route": "openai"}
  }'
```

Expected: routed via OpenAI models, unless budget caps prevent it (in which case the router falls back and logs the override rejection).

### 9.6. Verify / second opinion

```bash
curl -X POST http://localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "auto",
    "messages": [
      {"role": "user", "content": "[PIN] This is important context."},
      {"role": "assistant", "content": "Previous answer from provider A..."},
      {"role": "user", "content": "Can you verify that answer?"}
    ],
    "metadata": {"intent": "verify"}
  }'
```

Expected: router uses a different provider than the one used for the primary answer (based on metadata you pass in or internal hints) and returns a second opinion.

## 10. Command Center Dashboard (UI Contract)

The Command Center is a READ-ONLY dashboard.

Purpose:

- Visualize router activity.
- Show where inference is running.
- Display API usage and model routing.
- Show local GPU activity signals.

The dashboard MUST:

- Read from:
  - logs/router-requests.log
  - logs/router-errors.log
  - logs/router-context.log
  - /health endpoint

Display sections:

### A. Live Execution
- Current execution_target
- execution_host
- execution_mode
- active model

### B. Local GPU Status
- LM Studio (4090) status
- Ollama (2080 laptop) status
- Last activity timestamp

### C. API Usage
- Daily provider estimates
- Monthly estimates
- Provider distribution graph

### D. Router Activity Feed
- Last 20 routing events
- intent
- provider
- model
- tier

### E. System Health
- Router uptime
- Error count (last hour)
- Fallback events

Rules:

- Dashboard is OBSERVABILITY ONLY.
- No control actions.
- No destructive commands.
- Dashboard must degrade gracefully if logs are missing or empty.
---

This file is a living spec. As the implementation evolves, details in `router.yaml` may change, but the high-level behavior (routing, budget enforcement, token control, privacy constraints) should remain aligned with this document.
