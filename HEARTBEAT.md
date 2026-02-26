# HEARTBEAT.md

## Heartbeat Tasks (lightweight)

1. Check workspace state:
   - unread files in imports/uploaded-docs/
   - recent memory files for today

2. If new files exist:
   - move into correct imports/uploaded-docs/* folder
   - DO NOT process yet
   - just note paths in memory/YYYY-MM-DD.md

3. Chat archive digestion check:
   - Path:
     workspace/imports/chat-archives/
   - If files exist:
     - check LM Studio:
       http://10.10.10.98:1234/v1/models
     - if unavailable → check Ollama:
       http://10.10.10.175:11434
   - NEVER claim digestion is running.
   - ONLY report readiness or suggest starting Agent Zero worker.

4. Stay quiet unless:
   - new files detected
   - important reminder exists
   - user explicitly requested monitoring

Otherwise:
HEARTBEAT_OK