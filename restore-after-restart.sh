#!/bin/bash
# Run after any openclaw-gateway restart to restore session display names
echo '[restore] Waiting 6s for gateway to init...'
sleep 6
python3 /home/mikegg/.openclaw/workspace/restore-after-restart.py
