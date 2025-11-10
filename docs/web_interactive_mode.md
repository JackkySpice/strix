# Aura Web UI – Conversational Mode Notes

Date: 2025-11-10  
Branch: `cursor/check-mobile-responsiveness-and-terminal-interaction-1552`

## Summary
- Aura’s web console can now surface when the running Strix agent is paused waiting for operator guidance.
- A new API endpoint `POST /api/scans/{run_id}/messages` lets the web client submit user replies that resume the agent loop.
- Front-end composer switches between “launch scan” and “reply” modes with clear status banners, button labels, and placeholders.

## Backend Changes
- `strix/telemetry/tracer.py`
  - Track `root_agent_id` and `agent_waiting_since` so the UI can tell when the root agent is waiting.
  - Log `waiting_since` timestamps when agent status transitions to `"waiting"`.
- `strix/interface/web.py`
  - Added `ScanMessageRequest` validator for message content.
  - `ScanManager.send_message(...)` wraps `send_user_message_to_agent` with per-run locks and state checks.
  - `_serialize_scan(...)` now emits `waiting_for_input`, `waiting_since`, `root_agent_id`, and `root_agent_status`.
  - New route `POST /api/scans/{run_id}/messages` returns refreshed scan metadata after queuing a user reply.

## Front-End Changes
- Composer detects `waiting_for_input` and:
  - Allows submitting messages instead of launching new scans.
  - Updates placeholder text, button icons, and ARIA labels.
  - Shows banners/toasts explaining that the agent is paused.
- Chat feed inserts a high-visibility prompt reminding the user to respond when the agent is waiting.
- Sidebar and run header badge reflect `"waiting"` status.

## Testing Performed
- Server boots via `python3 -m uvicorn strix.interface.web:app --host 0.0.0.0 --port 8000`.
- `curl http://127.0.0.1:8000` (home template) and `curl http://127.0.0.1:8000/api/scans` (baseline API) succeed.
- Full conversational flow still needs validation with valid LLM credentials and an interactive scan (requires operator-side run).

## Outstanding Follow-Ups / TODO
- Run an end-to-end interactive scan to confirm:
  - Agent enters waiting state and UI switches to reply mode.
  - Posting to `/api/scans/{run_id}/messages` resumes the scan and UI returns to “running”.
- Decide whether to persist wait-state metadata across server restarts (currently in-memory).
- Consider rate limiting / auth for the new message endpoint before exposing publicly.
- Update external documentation / onboarding materials once the conversational mode is fully verified.

## Step-by-Step Tutorial (Local Preview)
1. **Prepare environment**
   - Export your LLM credentials (example):
     ```bash
     export STRIX_LLM="perplexity/sonar-pro"
     export LLM_API_KEY="pplx-XXXXXXX"
     ```
   - (Optional) create a virtualenv and install the project in editable mode:
     ```bash
     cd /workspace
     pip3 install .
     ```

2. **Launch the web server**
   ```bash
   python3 -m uvicorn strix.interface.web:app --host 0.0.0.0 --port 8000
   ```
   Leave this running; logs will show `Uvicorn running on http://0.0.0.0:8000`.

3. **Open the UI**
   - In Cursor: Web Preview → “Open Port” → 8000 → open link.
   - External SSH tunnel example:
     ```bash
     ssh -L 8000:127.0.0.1:8000 user@host
     ```
     then browse to `http://127.0.0.1:8000`.

4. **Start a scan**
   - In the composer, enter a target (e.g. `https://media.io`) and press send.
   - The left sidebar will list the run; the chat feed will stream activity.

5. **Respond when prompted**
   - When the agent pauses for input you’ll see:
     - Banner “Agent is waiting for your instructions…”
     - Composer placeholder changes to “Agent is waiting for your instructions…”
     - Chat feed shows a yellow prompt reminding you to reply.
   - Type your guidance in the composer and press send; the backend posts to `/api/scans/{run_id}/messages` and the scan resumes.

6. **Monitor progress**
   - The composer automatically reverts to “Scan in progress…” while the agent works.
   - Sidebar badges change from “waiting” → “running” → “completed/failed”.
   - The chat feed will show your messages (role `You`) and agent responses.

7. **Inspect results**
   - Once completed, use the sidebar to revisit past runs.
   - Download reports from `agent_runs/<run_id>/` on disk if needed.

8. **Shut down**
   - Stop the server with `Ctrl+C` (or `pkill -f "uvicorn strix.interface.web:app"`).
   - Clear credentials from the terminal if required (`unset LLM_API_KEY`).

## Known Risks
- If the agent crashes while waiting, UI may still show “waiting for input” until the next status refresh.
- Large terminal outputs may make `/api/scans/{run_id}/events` heavy; consider pagination if this becomes an issue.
- Multiple browser tabs replying simultaneously rely on the per-run asyncio lock but still need testing under load.

