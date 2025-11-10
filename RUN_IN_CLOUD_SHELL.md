## Strix Web UI (Aura) – Cloud Shell Guide

This repo adds a FastAPI-based web wrapper and the Aura chat UI so you can run Strix in Google Cloud Shell and control it from a phone. Follow the steps below whenever you set up a fresh Cloud Shell session.

---

### 1. Launch Cloud Shell
1. Open [https://shell.cloud.google.com](https://shell.cloud.google.com) and authorize your Google account.
2. If prompted, choose the project that should own the VM (the default ephemeral VM is fine).

---

### 2. Clone or update your fork

If this is the first time:
```bash
git clone https://github.com/JackkySpice/strix.git
cd strix
```

If you already cloned the fork earlier:
```bash
cd strix
git pull origin your-branch-name
```
Replace `your-branch-name` with the branch that contains the web UI work (e.g. `cursor/adapt-cloud-app-for-mobile-7c10`).

> **Tip**: Cloud Shell comes with Git preinstalled. Your fork lives under `github.com/JackkySpice/strix`, so cloning over HTTPS works out of the box. If you prefer SSH, add your public key to GitHub first.

---

### 3. Install dependencies

Cloud Shell already has Python 3.11+. Install once per VM session:
```bash
poetry install
```
If Poetry is not available:
```bash
pip install --user poetry
poetry install
```
You can also fall back to plain pip:
```bash
pip install -e .
```

---

### 4. Configure environment variables

Export the same values you currently use for the CLI:
```bash
export STRIX_LLM="perplexity/sonar-pro"
export LLM_API_KEY="pplx-..."          # rotate if the old key leaked
# Optional extras
# export PERPLEXITY_API_KEY="..."
# export LLM_API_BASE="..."            # only if you target a custom endpoint
```
These exports only last for the current shell session. Add them to `~/.bashrc` if you want them to persist.

---

### 5. Start the web server

From the repo root:
```bash
poetry run uvicorn strix.interface.web:app --host 0.0.0.0 --port 8080
```

The first run may pause for 1–2 minutes while Docker pulls the Strix image. Subsequent runs reuse the cached image.

If you see errors about Docker or env vars, fix them and rerun the command.

---

### 6. Open the Aura UI (mobile friendly)

1. In the Cloud Shell toolbar, click **Web Preview → Preview on port 8080**.
2. A new browser tab opens with the `https://8080-dot-<your-cloudshell-id>.appspot.com/` URL.
3. Bookmark that URL on your phone; it stays valid for the lifetime of the Cloud Shell VM.

You’ll see the Aura-styled chat layout: sidebar shows recent scans; main panel is the agent feed.

---

### 7. Run a scan from the UI

1. Type a target URL or domain (e.g. `https://media.io`) in the bottom input.
2. Press **Send**. The banner shows warm-up messages while Docker starts Strix.
3. Real-time events (tool usage, findings, summaries) appear in the chat feed.
4. Completed results are saved to `agent_runs/<run-id>` just like the CLI.

Only one scan runs at a time. Wait for the status badge to read `completed` or `failed` before launching another target.

---

### 8. Inspect results

- On the VM: `ls agent_runs/<run-id>` – contains the markdown report and vulnerabilities.
- Via API:
  - `GET /api/scans/<run-id>` – metadata, vulnerability list, final report.
  - `GET /api/scans/<run-id>/events` – chronological events (chat, tools, vulns).
  - `GET /api/scans/<run-id>/report` – final markdown summary.

Use `curl` or open these URLs in the Web Preview tab while the server is running.

---

### 9. Stopping and restarting

- Stop the server with `Ctrl+C`.
- Restart anytime with the `uvicorn` command above.
- Cloud Shell VMs automatically shut down after 30 minutes of inactivity; when that happens, repeat steps 1–6.

---

### 10. Known limitations / next steps

- **Single scan at a time**: Queueing/sub-agent messaging via the UI is not implemented yet.
- **Web targets only**: Repository/local directory targets still require the CLI/TUI.
- **No auth**: The FastAPI app is open on the preview URL. Add bearer-token checks if you ever expose it outside Cloud Shell.
- **No automated testing**: FastAPI module compiles, but hasn’t been run end-to-end in this environment. Use the guide above and report any runtime issues.

---

### Quick reference commands

```bash
# Clone
git clone https://github.com/JackkySpice/strix.git
cd strix

# Update
git pull origin cursor/adapt-cloud-app-for-mobile-7c10

# Dependencies
poetry install

# Env vars
export STRIX_LLM="perplexity/sonar-pro"
export LLM_API_KEY="..."

# Start server
poetry run uvicorn strix.interface.web:app --host 0.0.0.0 --port 8080
```

Keep this walkthrough in the repo so future agents (or you) have the full context for running the Aura UI in Cloud Shell.
