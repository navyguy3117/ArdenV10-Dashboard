# Dashboard Stylist Skill

## Purpose
UI-only specialist responsible for polishing and completing the Arden Router Command Center dashboard.

## Scope

Allowed:
* /home/mikegg/.openclaw/workspace/dashboard/**

Read-only reference:
* /home/mikegg/.openclaw/workspace/router/**

Forbidden:
* router edits
* routing logic changes
* secrets/env/API keys
* system services
* cron/system configs

## Responsibilities
1. Ensure Tailwind/Vite/PostCSS pipeline works.
2. Improve layout readability.
3. Apply consistent neon/glass styling.
4. Add subtle motion respecting prefers-reduced-motion.
5. Validate build stability.

## Workflow
* Make small reversible changes.
* Verify visually after changes.
* Avoid massive refactors.
* Stop when Definition of Done is met.

## Definition of Done
* Tailwind styles visibly active
* No plain/unstyled HTML appearance
* Balanced layout
* Readable typography
* Consistent neon/glass styling
* Subtle motion only
* npm run build succeeds

## Output After Work Session
Return:
* files changed
* what was broken
* what was fixed
* run command
* expected visuals
