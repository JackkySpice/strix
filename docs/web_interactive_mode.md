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

## Known Risks
- If the agent crashes while waiting, UI may still show “waiting for input” until the next status refresh.
- Large terminal outputs may make `/api/scans/{run_id}/events` heavy; consider pagination if this becomes an issue.
- Multiple browser tabs replying simultaneously rely on the per-run asyncio lock but still need testing under load.

