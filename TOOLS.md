# TOOLS.md - Local Environment & Commands

## Purpose
Environment-specific notes, shortcuts, and custom command behavior.

---

## Core Hosts

### LM Studio (4090)
- http://10.10.10.98:1234
- Primary local inference
- Use first for archive digestion

### Ollama (2080 laptop)
- http://10.10.10.175:11434
- Fallback if LM Studio unavailable

---

## Workspace Paths

### Imports (PRIVATE)
workspace/imports/

Subfolders:
- uploaded-docs/images
- uploaded-docs/pdf
- uploaded-docs/spreadsheets
- uploaded-docs/text
- uploaded-docs/mixed

Rule:
- Anything inside imports/ = LOCAL ONLY
- Never send to external APIs.

---

## Chat Archives

Path:
workspace/imports/chat-archives/

Purpose:
- Local digestion only
- Generate MD summaries:
  - mood
  - tone
  - behavioral patterns
  - adaptation notes

Processing order:
1. LM Studio (4090)
2. Ollama fallback

---

## Custom Commands

### /new
Behavior:
- summarize current session
- write summary to memory/YYYY-MM-DD.md
- then start fresh chat

Purpose:
- prevent context loss
- reduce sluggish sessions

---

## Agent Roles

### Arden (main)
- daily chat partner
- planning
- troubleshooting
- memory management

### Agent Zero (worker)
- long-running processing
- archive digestion
- background jobs with verifiable output

---

## Command Center Dashboard

### Location
- Backend: workspace/command_center/main.py (FastAPI on port 3000)
- Frontend: workspace/command_center/static/index.html (single-page app)
- Database: workspace/command_center/command_center.db (SQLite)

### Quick Reference
Full technical docs (all API endpoints, WebSocket events, grid layout,
auth system, env vars, troubleshooting): see **DASHBOARD-REFERENCE.md**

### Common Issues
- Dashboard wont load → check if server is running: systemctl --user status arden-command-center
- Tiles stacking wrong → click RESET TILES button in top nav
- Auth locked out → unset CC_PASSWORD in .env and restart
- WebSocket disconnects → check /health endpoint first

## Rules

- Never claim work is running without evidence.
- One command at a time by default.
- Keep responses short unless Mike asks for detail.