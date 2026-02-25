#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# install.sh — Arden // Command Center Installation Script
# Target: WSL2 Ubuntu 24.04
# Usage: bash install.sh
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

WORKSPACE="/home/mikegg/.openclaw/workspace"
APP_DIR="$WORKSPACE/command_center"
VENV_DIR="$APP_DIR/venv"
SERVICE_NAME="arden-command-center"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PYTHON="python3"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
AMBER='\033[0;33m'; NC='\033[0m'; BOLD='\033[1m'

echo -e "${CYAN}${BOLD}"
echo "  ╔═══════════════════════════════════════════╗"
echo "  ║   ARDEN // COMMAND CENTER  INSTALLER      ║"
echo "  ║   Version 1.0.0 · WSL2 Ubuntu 24.04       ║"
echo "  ╚═══════════════════════════════════════════╝"
echo -e "${NC}"

log()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()   { echo -e "${AMBER}[!]${NC} $*"; }
error()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }
info()   { echo -e "${CYAN}[i]${NC} $*"; }

# ── 1. Check we're in WSL2 ────────────────────────────────────
if ! grep -qi microsoft /proc/version 2>/dev/null; then
  warn "Not running in WSL2 — continuing anyway but paths may differ"
fi

# ── 2. Create workspace directories ──────────────────────────
info "Creating workspace directories..."
mkdir -p "$WORKSPACE/avatars"
mkdir -p "$WORKSPACE/imports/uploaded-docs"
mkdir -p "$WORKSPACE/logs"
mkdir -p "$APP_DIR/static"
log "Workspace directories ready"

# ── 3. Copy application files ─────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
info "Copying application files from $SCRIPT_DIR to $APP_DIR..."
for f in main.py database.py metrics.py avatar.py requirements.txt; do
  if [ -f "$SCRIPT_DIR/$f" ]; then
    cp "$SCRIPT_DIR/$f" "$APP_DIR/$f"
    log "Copied: $f"
  else
    warn "Missing: $f (skipping)"
  fi
done
if [ -f "$SCRIPT_DIR/static/index.html" ]; then
  cp "$SCRIPT_DIR/static/index.html" "$APP_DIR/static/index.html"
  log "Copied: static/index.html"
fi

# Copy .env only if not already present
if [ ! -f "$APP_DIR/.env" ]; then
  if [ -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env" "$APP_DIR/.env"
    log "Copied: .env"
  elif [ -f "$SCRIPT_DIR/.env.example" ]; then
    cp "$SCRIPT_DIR/.env.example" "$APP_DIR/.env"
    log "Copied .env.example → .env (please review settings)"
  fi
else
  log ".env already exists — not overwriting"
fi

# Copy quick_launch.json to workspace root
if [ ! -f "$WORKSPACE/quick_launch.json" ]; then
  if [ -f "$SCRIPT_DIR/quick_launch.json" ]; then
    cp "$SCRIPT_DIR/quick_launch.json" "$WORKSPACE/quick_launch.json"
    log "Copied: quick_launch.json"
  fi
fi

# ── 4. Install system dependencies ────────────────────────────
info "Checking Python..."
if ! command -v python3 &>/dev/null; then
  info "Installing Python 3..."
  sudo apt-get update -qq
  sudo apt-get install -y python3 python3-pip python3-venv
fi
PYTHON_VERSION=$($PYTHON --version 2>&1)
log "Using: $PYTHON_VERSION"

# ── 5. Create virtual environment ─────────────────────────────
info "Setting up Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
  $PYTHON -m venv "$VENV_DIR"
  log "Virtual environment created"
else
  log "Virtual environment already exists"
fi

# ── 6. Install Python dependencies ────────────────────────────
info "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
log "Dependencies installed"

# ── 7. Install systemd service ────────────────────────────────
info "Installing systemd service..."
CURRENT_USER=$(whoami)
cat > /tmp/${SERVICE_NAME}.service << EOF
[Unit]
Description=Arden // Command Center
After=network.target
StartLimitIntervalSec=30
StartLimitBurst=5

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${VENV_DIR}/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=arden-command-center

[Install]
WantedBy=multi-user.target
EOF

# In WSL2, systemd may not be available — try both
if command -v systemctl &>/dev/null && systemctl --user status &>/dev/null 2>&1; then
  # User-level systemd
  mkdir -p "$HOME/.config/systemd/user"
  cp /tmp/${SERVICE_NAME}.service "$HOME/.config/systemd/user/${SERVICE_NAME}.service"
  systemctl --user daemon-reload
  systemctl --user enable "${SERVICE_NAME}"
  systemctl --user start "${SERVICE_NAME}" || warn "Could not start service — use start.sh manually"
  log "Systemd user service installed and started"
elif sudo systemctl status &>/dev/null 2>&1; then
  # System-level systemd
  sudo cp /tmp/${SERVICE_NAME}.service "$SERVICE_FILE"
  sudo systemctl daemon-reload
  sudo systemctl enable "${SERVICE_NAME}"
  sudo systemctl start "${SERVICE_NAME}" || warn "Could not start service — use start.sh manually"
  log "Systemd system service installed"
else
  warn "systemd not available — installing screen/tmux fallback"
  install_screen_fallback
fi

# ── 8. Create start/stop helper scripts ───────────────────────
cat > "$APP_DIR/start.sh" << 'STARTEOF'
#!/usr/bin/env bash
# Start Command Center (fallback for systems without systemd)
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$APP_DIR/venv"
LOG_FILE="$APP_DIR/command_center.log"

if command -v screen &>/dev/null; then
  screen -dmS arden-cc bash -c "cd $APP_DIR && $VENV/bin/python main.py 2>&1 | tee -a $LOG_FILE"
  echo "Started in screen session: arden-cc"
  echo "Attach with: screen -r arden-cc"
elif command -v tmux &>/dev/null; then
  tmux new-session -d -s arden-cc "cd $APP_DIR && $VENV/bin/python main.py 2>&1 | tee -a $LOG_FILE"
  echo "Started in tmux session: arden-cc"
  echo "Attach with: tmux attach -t arden-cc"
else
  nohup "$VENV/bin/python" main.py >> "$LOG_FILE" 2>&1 &
  echo "Started as background process (PID $!)"
  echo "Log: $LOG_FILE"
fi
STARTEOF

cat > "$APP_DIR/stop.sh" << 'STOPEOF'
#!/usr/bin/env bash
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Kill screen session
screen -S arden-cc -X quit 2>/dev/null && echo "Stopped screen session" && exit 0
# Kill tmux session
tmux kill-session -t arden-cc 2>/dev/null && echo "Stopped tmux session" && exit 0
# Kill by port
fuser -k 3000/tcp 2>/dev/null && echo "Killed process on port 3000" || echo "No process found on port 3000"
STOPEOF

chmod +x "$APP_DIR/start.sh" "$APP_DIR/stop.sh"
log "start.sh and stop.sh created"

# ── 9. Rename avatar images to have correct prefixes ──────────
info "Checking avatar files..."
AVATARS="$WORKSPACE/avatars"
# Rename unprefixed PNGs to idle- prefix so they are picked up
for f in "$AVATARS"/*.png; do
  [ -f "$f" ] || continue
  basename=$(basename "$f")
  name="${basename%.*}"
  # Check if it already has a mood prefix
  if [[ ! "$name" =~ ^(idle|happy|thinking|alert|error|bored)- ]]; then
    newname="idle-${basename}"
    mv "$f" "$AVATARS/$newname" 2>/dev/null || true
    log "Renamed: $basename → $newname"
  fi
done

# ── 10. Verify installation ────────────────────────────────────
echo ""
echo -e "${CYAN}${BOLD}═══ Installation Complete ═══${NC}"
echo ""
echo -e "  ${GREEN}Dashboard:${NC}  http://localhost:3000"
echo -e "  ${GREEN}API docs:${NC}   http://localhost:3000/docs"
echo -e "  ${GREEN}WebSocket:${NC}  ws://localhost:3000/ws"
echo ""
echo -e "  ${CYAN}Manual start:${NC}  bash $APP_DIR/start.sh"
echo -e "  ${CYAN}Manual stop:${NC}   bash $APP_DIR/stop.sh"
echo ""

# Try to test if it's already running
sleep 2
if curl -s http://localhost:3000/ -o /dev/null -w "%{http_code}" | grep -q "200"; then
  log "Dashboard is live at http://localhost:3000"
else
  info "Dashboard starting... check http://localhost:3000 in a moment"
fi

echo ""
echo -e "${AMBER}REMINDER:${NC} Edit $APP_DIR/.env to configure paths and budget limits"
echo ""
