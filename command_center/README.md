# Arden // Command Center

Personal AI operations dashboard. Local-only, self-hosted, built for one user.
FastAPI backend + single-file frontend. Served on **port 3000** from WSL2 Ubuntu 24.04.

---

## Quick Start

```bash
cd /home/mikegg/.openclaw/workspace/command_center
cp .env.example .env        # then fill in your keys (see below)
pip install -r requirements.txt
python main.py
```

Open: **http://localhost:3000**

---

## API Keys — Where to Set Them

All keys live in one file: **`command_center/.env`**

| Key | What it's for | Where to get it |
|-----|--------------|-----------------|
| `OPENAI_API_KEY` | OpenAI chat (GPT-4o etc.) | platform.openai.com → API Keys |
| `ANTHROPIC_API_KEY` | Anthropic chat (Claude) | console.anthropic.com → API Keys |
| `OPENROUTER_API_KEY` | OpenRouter (multi-model) | openrouter.ai → Keys |
| `GOOGLE_API_KEY` | Gemini chat + YouTube browser | console.cloud.google.com → Credentials |
| `ELEVENLABS_API_KEY` | TTS voice (speak button + auto-speak) | elevenlabs.io → Profile → API Keys |
| `ELEVENLABS_VOICE_ID` | Default voice ID | elevenlabs.io → Voices → copy ID |
| `GIPHY_API_KEY` | Giphy GIF search + TV mode | developers.giphy.com → Create App |
| `TELEGRAM_BOT_TOKEN` | Telegram bot integration | @BotFather on Telegram |

### Rotating a Key

1. Open `.env` in any text editor
2. Replace the old value — format is always `KEY_NAME=new_value_here`
3. Restart the server:
```bash
pkill -f "python main.py"
cd /home/mikegg/.openclaw/workspace/command_center && python main.py &
```

---

## Google API Key — Required APIs

Your `GOOGLE_API_KEY` must have these APIs enabled in Google Cloud Console
([console.cloud.google.com](https://console.cloud.google.com)):

- **Generative Language API** — for Gemini chat
- **YouTube Data API v3** — for YouTube browser (trending + search)

If you see "blocked" errors, go to **Credentials → your key → API restrictions**
and add both APIs, or set to unrestricted (safe for a local-only dashboard).

---

## ElevenLabs Voice

To change the default TTS voice:
1. Go to [elevenlabs.io](https://elevenlabs.io) → Voices
2. Find the voice → copy its **Voice ID**
3. In `.env`, update: `ELEVENLABS_VOICE_ID=paste_id_here`
4. The voice dropdown in chat lets you switch per-session without restarting

**If you get `quota_exceeded` errors:** your API key has a credit cap.
Go to ElevenLabs → Settings → API Keys → edit your key → remove or raise the credit limit.

---

## Architecture

```
command_center/
├── main.py              # FastAPI backend — all /api/* endpoints
├── static/
│   └── index.html       # Entire frontend (HTML + CSS + JS, single file)
├── .env                 # API keys — never committed to git
├── .env.example         # Safe template to copy from
├── requirements.txt     # Python dependencies
└── command_center.db    # SQLite — tasks, jobs, agent state
```

**All frontend code is in one file:** `static/index.html`
**All backend code is in one file:** `main.py`

---

## Troubleshooting

### Server won't start
```bash
ss -tlnp | grep 3000          # check what's on port 3000
pkill -f "python main.py"     # kill old process
python main.py                # restart
```

### Chat returns no response
- Check the provider badge in the header — red = bad key
- Verify the correct key is set in `.env` for the provider you're using
- Gemini requires `GOOGLE_API_KEY` with Generative Language API enabled

### YouTube browser shows error
- Confirm **YouTube Data API v3** is enabled in Google Cloud Console
- Confirm `GOOGLE_API_KEY` is not restricted away from YouTube Data API v3
- Wait 2-3 minutes after enabling — Google takes time to propagate

### TTS (speak button) silent
- Click anywhere on the page first — browser requires user interaction before audio
- Check ElevenLabs key quota: elevenlabs.io → Settings → API Keys
- `quota_exceeded` = key has a credit cap, raise or remove it

### Mic button does nothing
- Must use **http://localhost:3000** — mic requires a secure context
- LAN IP (172.x.x.x:3000) will NOT work — browser security restriction
- Fix: use ElevenLabs STT backend swap (planned feature)

### Tiles look broken / overlapping
- Click **RESET TILES** in the header → restores default layout
- If still broken: F12 console → check for JS errors

### Giphy not loading
- Check `GIPHY_API_KEY` in `.env` has no `#` prefix (that makes it a comment)
- New key: developers.giphy.com

---

## Running as a Service (auto-start with WSL2)

```bash
sudo cp arden-command-center.service /etc/systemd/system/
sudo systemctl enable arden-command-center
sudo systemctl start arden-command-center
sudo systemctl status arden-command-center   # check it's running
```

---

## Backups

The `.env` file and database are gitignored — back them up separately:

```bash
# Copy to Windows Desktop
cp .env /mnt/c/Users/MikeGG/Desktop/arden-env-backup.txt
cp command_center.db /mnt/c/Users/MikeGG/Desktop/arden-db-backup.db
```

Key files to protect:
| File | Contains |
|------|----------|
| `.env` | All API keys — keep private |
| `command_center.db` | Tasks, jobs, saved state |
| `static/index.html` | All frontend code |
| `main.py` | All backend code |
