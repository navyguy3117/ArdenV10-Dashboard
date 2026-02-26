# START-HERE.md

Welcome to your OpenClaw workspace.

This folder is your **safe workspace** where Arden (your AI familiar) lives and works. You interact with Arden through two main surfaces:

- **WebUI (control UI / this interface)**
- **Telegram (chat with Arden)**

Both of these are part of your "safe workspace" for experimentation, planning, and automation.

---

## What this workspace is

Location on disk:
- `/home/mikegg/.openclaw/workspace`

Key files:
- `AGENTS.md` – Instructions for how Arden should treat this workspace and memory
- `SOUL.md` – Arden's personality / behavior
- `IDENTITY.md` – Who Arden is
- `USER.md` – Who you are (Mike / Beanz / Jumpingbeanz)
- `HEARTBEAT.md` – Optional periodic checks/tasks
- `TOOLS.md` – Local notes about tools/devices
- `DASHBOARD-REFERENCE.md` – Full technical reference for the Command Center dashboard (endpoints, tiles, auth, troubleshooting)
-  – Full technical reference for the Command Center dashboard (endpoints, tiles, auth, troubleshooting)
- `memory/` – Daily and long‑term notes (created as needed)

You can safely:
- Create, edit, and delete files here
- Let Arden read and organize things
- Use it as a scratchpad for projects, ideas, and experiments

Be more cautious with anything **outside** this folder (Arden will ask or be conservative there).

---

## WebUI vs Telegram

### WebUI (control UI)
Use this when you:
- Want to do **workspace-level work** (files, commands, skills)
- Are at your computer and want more of an "IDE for your AI"
- Need to see file changes, logs, or structured output

Typical WebUI tasks:
- "Create a new project folder and scaffold files for X"
- "Search the workspace for references to Y"
- "Run this command and summarize the result"
- "Refactor these files / update this config"

### Telegram
Use this when you:
- Are away from the computer but still want Arden's brain
- Want quick answers, planning help, or reminders
- Prefer a more casual, chatty interaction

Typical Telegram tasks:
- "Help me plan my evening / weekend"
- "Summarize this article / idea"
- "Brainstorm WoW builds / strategies"
- Quick Q&A, notes, or decisions

Telegram is more about **conversation**; WebUI is more about **workspace operations**.

---

## How Arden thinks about "safe workspace"

When you say "safe workspace", Arden assumes:
- Interactions via **WebUI** and **Telegram with Arden** are safe contexts
- Inside `/home/mikegg/.openclaw/workspace` is safe to read/modify
- External/public actions (emails, social posts, anything outside your control) require extra caution or explicit confirmation

Arden's default stance:
- **Bold inside** this workspace
- **Careful outside** it

### Safety rules for this workspace

These are hard rules Arden follows here:
- **Never access anything outside** `/home/mikegg/.openclaw/workspace` **unless you explicitly ask.**
- **Never use `sudo`.**
- **Ask before deleting or moving files.**
- **Prefer explaining planned actions before executing commands**, especially for anything non-trivial.

---

## Getting started

Some simple things you can ask Arden (via WebUI):

- "List projects or files here and suggest an organization structure"
- "Set up a notes system for me (daily notes + long‑term memory)"
- "Scan AGENTS.md, SOUL.md, USER.md and suggest tweaks"
- "Create a template for tracking WoW characters / builds"

And via Telegram:
- "Help me plan tomorrow in 5 steps"
- "Capture this as a note and store it in today's memory file"
- "Remind me what we decided about X" (Arden will check memory files)

---

## Where to change behavior

If you want to tweak how Arden behaves:
- Edit **SOUL.md** for personality and general rules
- Edit **AGENTS.md** for workspace-wide practices
- Edit **USER.md** for info about you
- Use **HEARTBEAT.md** to define periodic checks

Change the files, then talk to Arden in WebUI or Telegram about what you changed.

## Memory Flow (Important)

Arden builds understanding over time using:

- memory/YYYY-MM-DD.md (daily context)
- MEMORY.md (long-term distilled patterns)
- MODE.md / TONE.md (if present) override default behavior rules.

Tone, speech patterns, and working style should be learned from these files — not guessed.

---

## TL;DR
- This folder is Arden's home and your safe sandbox.
- WebUI = structured, workspace-centric work.
- Telegram = conversational, on-the-go help.
- You can evolve this setup any time by editing the core files above.
