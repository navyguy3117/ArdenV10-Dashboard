#!/usr/bin/env python3
"""
Run after any openclaw-gateway restart to restore session state.
Usage: python3 ~/.openclaw/workspace/restore-after-restart.py
"""
import json
import sys

SESSIONS = "/home/mikegg/.openclaw/agents/main/sessions/sessions.json"

def restore():
    with open(SESSIONS) as f:
        data = json.load(f)

    session = data.setdefault("agent:main:main", {})
    session["displayName"] = "Arden"

    with open(SESSIONS, "w") as f:
        json.dump(data, f, indent=2)

    print("  [restore] displayName = 'Arden' set on agent:main:main ✓")
    print("  [restore] Reload Brave tab at http://127.0.0.1:18789")

if __name__ == "__main__":
    restore()
