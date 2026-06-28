# Docker Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize the network-assistant MCP server and React dashboard and deploy them to the home server at `homeserver.lan` so the server is always-on.

**Architecture:** Multi-stage Docker build — Stage 1 uses `node:20-slim` to build the React dashboard, Stage 2 uses `python:3.11-slim` to run the MCP server and serve the built dashboard. `network_mode: host` gives the container access to the host ARP table, raw sockets (ping), and multicast (UPnP SSDP). `config.json` and `devices.json` are volume-mounted from the host so secrets never enter the image and device labels persist across rebuilds.

**Tech Stack:** Docker, Docker Compose, Node 20, Python 3.11

## Global Constraints

- Base images: `node:20-slim` (builder), `python:3.11-slim` (runtime)
- `network_mode: host` — required; do not use bridge networking
- `config.json` mounted read-only; `devices.json` mounted read-write
- Secrets (`config.json`, `devices.json`) are never `COPY`ed into the image
- MCP URL after migration: `http://homeserver.lan:8000/mcp`
- Home server IP: `192.168.0.160`, hostname: `homeserver.lan`

---

### Task 1: Dockerfile, docker-compose.yml, and .dockerignore

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

**Interfaces:**
- Produces: a buildable Docker image that serves `src/server.py` on port 8000 with `dashboard/dist/` available at `/app/dashboard/dist/`

- [ ] **Step 1: Create `.dockerignore`**

```
.venv/
node_modules/
dashboard/node_modules/
dashboard/dist/
config.json
devices.json
tests/
docs/
__pycache__/
*.pyc
.pytest_cache/
tmp_*.py
CLAUDE.md
.claude/
.superpowers/
.DS_Store
*.egg-info/
build/
dist/
.env
README.md
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
# Stage 1: build React dashboard
FROM node:20-slim AS dashboard-builder
WORKDIR /app/dashboard
COPY dashboard/package*.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY --from=dashboard-builder /app/dashboard/dist ./dashboard/dist/
EXPOSE 8000
CMD ["python", "-m", "src.server"]
```

Note: `src/api.py` resolves the dashboard path as `Path(__file__).parent.parent / "dashboard" / "dist"` — with `WORKDIR /app` this becomes `/app/dashboard/dist`, which matches the `COPY` destination above.

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  network-assistant:
    build: .
    network_mode: host
    restart: unless-stopped
    volumes:
      - ./config.json:/app/config.json:ro
      - ./devices.json:/app/devices.json
```

`network_mode: host` is required for three reasons:
- `arp -an` in `devices.py` reads the host ARP table — invisible through bridge NAT
- `ping`/`traceroute` in `diagnostics.py` need raw socket access (`NET_RAW`)
- `miniupnpc` in `upnp.py` uses SSDP multicast discovery — blocked by bridge networking

- [ ] **Step 4: Validate — build the image locally**

If Docker Desktop is installed on the Mac:

```bash
cd /Users/taylorgay/Documents/GitHub/network-assistant
docker build .
```

Expected: build completes with no errors. The Node stage will run `npm ci` and `npm run build`; the Python stage will run `pip install`. Final output should be a tagged image ID.

If Docker Desktop is not installed on the Mac, skip this step — Task 3 validates the build on the home server.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "feat: add Dockerfile and docker-compose for home server deployment"
```

---

### Task 2: Update Mac-side config

**Files:**
- Modify: `.claude/mcp_settings.json`
- Modify: `.claude/settings.json`
- Delete: `start.sh`

**Interfaces:**
- Consumes: `homeserver.lan:8000/mcp` (from Task 1 + Task 3 deployment)
- Produces: Claude Code pointing at the home server; no more local server startup needed

- [ ] **Step 1: Update `.claude/mcp_settings.json`**

Replace the entire file with:

```json
{
  "mcpServers": {
    "network-assistant": {
      "type": "streamable-http",
      "url": "http://homeserver.lan:8000/mcp"
    }
  }
}
```

- [ ] **Step 2: Update `.claude/settings.json` SessionStart hook**

The hook currently checks `http://localhost:8000/mcp`. Update the `command` field to check `homeserver.lan:8000` and update the warning message. The hook structure stays the same — only the URL and message change.

Find this line in `.claude/settings.json`:
```
"command": "curl -s --max-time 1 http://localhost:8000/mcp -o /dev/null 2>&1; [ $? -eq 7 ] && echo '{\"systemMessage\": \"MCP server not running — start it before using network tools: .venv/bin/python -m src.server\"}'",
```

Replace with:
```
"command": "curl -s --max-time 1 http://homeserver.lan:8000/mcp -o /dev/null 2>&1; [ $? -eq 7 ] && echo '{\"systemMessage\": \"MCP server unreachable — check that the home server (192.168.0.160) is up and the container is running\"}'",
```

- [ ] **Step 3: Delete `start.sh`**

```bash
rm start.sh
```

`start.sh` existed solely to start the Python server before opening Claude. The server now runs on the home server and is always-on.

- [ ] **Step 4: Validate JSON**

```bash
python3 -c "import json; json.load(open('.claude/mcp_settings.json')); print('mcp_settings.json: OK')"
python3 -c "import json; json.load(open('.claude/settings.json')); print('settings.json: OK')"
```

Expected:
```
mcp_settings.json: OK
settings.json: OK
```

- [ ] **Step 5: Commit**

```bash
git add .claude/mcp_settings.json .claude/settings.json
git rm start.sh
git commit -m "chore: point MCP client at homeserver.lan:8000, remove start.sh"
```

Note: `.claude/settings.json` is not gitignored — it's checked in (confirmed: it was in the existing git tree). `start.sh` was also checked in and must be `git rm`'d not just `rm`'d.

---

### Task 3: Deploy to home server and verify

**Files:**
- No files created or committed — this is a deployment task

**Interfaces:**
- Consumes: commits from Task 1 and Task 2, `config.json` and `devices.json` from the Mac

- [ ] **Step 1: Push commits to GitHub**

On the Mac:

```bash
git push
```

- [ ] **Step 2: SSH into the home server and clone the repo**

```bash
ssh <user>@homeserver.lan
git clone https://github.com/taylorjgay/network-assistant.git ~/network-assistant
cd ~/network-assistant
```

Replace `<user>` with your home server username (e.g., `taylor`).

- [ ] **Step 3: Copy gitignored files from the Mac**

In a separate terminal on the Mac:

```bash
cd /Users/taylorgay/Documents/GitHub/network-assistant
scp config.json devices.json <user>@homeserver.lan:~/network-assistant/
```

These files are gitignored and never in the repo — they must be copied manually. `config.json` holds device credentials; `devices.json` holds the 60+ device labels.

- [ ] **Step 4: Start the container**

On the home server:

```bash
cd ~/network-assistant
docker compose up --build -d
```

Expected: Docker builds the image (Node stage + Python stage), then starts the container. First build takes 2–5 minutes (npm ci + pip install). Subsequent builds are faster due to layer caching.

- [ ] **Step 5: Check container logs**

```bash
docker compose logs -f network-assistant
```

Expected: uvicorn startup message, then the server listening on port 8000. Press Ctrl+C to stop following logs.

- [ ] **Step 6: Smoke-test the server from the Mac**

```bash
curl -s -o /dev/null -w "%{http_code}" http://homeserver.lan:8000/mcp
```

Expected: `406` — the server is running but rejects a plain curl (it expects a proper MCP handshake). This is the same response as before when running locally.

- [ ] **Step 7: Verify MCP tools in Claude Code**

Open a new Claude Code session (in the network-assistant repo). The SessionStart hook will check `homeserver.lan:8000` — no warning should appear if the container is running.

Ask Claude to call a network tool, e.g.:

> "Get Pi-hole stats"

Expected: Claude calls `get_pihole_stats` via MCP and returns live data from `192.168.0.200`. If this works, the migration is complete.

- [ ] **Step 8: Verify the dashboard**

Open `http://homeserver.lan:8000` in a browser.

Expected: Network Assistant dashboard loads, all 5 tabs functional (Overview, Network, DNS, Firewall, Diagnostics).
