# Docker Migration — Design Spec

**Date:** 2026-06-28

## Background

The network-assistant MCP server and React dashboard currently run on the Mac (`localhost:8000`), requiring manual startup before each Claude Code session. A home server (Intel N100 mini PC, `192.168.0.160`, `homeserver.lan`) is now on the network running Docker. Migrating to the home server makes the server always-on — no manual startup, Claude Code connects immediately.

## Docker Setup

### `Dockerfile` (multi-stage)

**Stage 1 — dashboard builder:** `node:20-slim`. Copies `dashboard/package*.json`, runs `npm ci`, copies `dashboard/`, runs `npm run build`. Produces `dashboard/dist/`.

**Stage 2 — Python runtime:** `python:3.11-slim`. Installs Python dependencies from `requirements.txt` (no `.venv` — installs into system Python). Copies `src/`. Copies `dashboard/dist/` from Stage 1. Exposes port 8000. `CMD ["python", "-m", "src.server"]`.

### `docker-compose.yml`

Single service `network-assistant`:
- `build: .`
- `network_mode: host` — required for ARP (`arp -an` reads host ARP table), ping/traceroute (NET_RAW), and miniupnpc SSDP discovery (multicast). Bridge networking breaks all three.
- `restart: unless-stopped` — auto-starts on boot, survives reboots
- Volume mounts:
  - `./config.json:/app/config.json:ro` — credentials (read-only; never baked into image)
  - `./devices.json:/app/devices.json` — device labels (read-write; dashboard updates this at runtime)

### `.dockerignore`

Excludes: `.venv/`, `node_modules/`, `dashboard/node_modules/`, `dashboard/dist/`, `config.json`, `devices.json`, `tests/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `tmp_*.py`, `CLAUDE.md`, `.claude/`, `.DS_Store`

## Mac-Side Changes

### `.claude/mcp_settings.json`

Change `url` from `http://localhost:8000/mcp` to `http://homeserver.lan:8000/mcp`.

### `.claude/settings.json` — SessionStart hook

Update the curl URL from `http://localhost:8000/mcp` to `http://homeserver.lan:8000/mcp`. Since the server is always-on, the warning fires only if the home server is unreachable.

### `start.sh` — deleted

The script's sole purpose was starting the Python server before opening Claude. With the server always-on on the home server, it serves no function.

## Deployment Workflow

### Initial setup on home server (one-time)

```bash
git clone https://github.com/taylorjgay/network-assistant.git ~/network-assistant
cd ~/network-assistant
docker compose up --build -d
```

Before running compose, copy the gitignored files from the Mac:
```bash
scp config.json devices.json user@homeserver.lan:~/network-assistant/
```

`config.json` and `devices.json` are never committed — they live on the host and are volume-mounted into the container.

### Deploying updates

After `git push` from the Mac:
```bash
ssh user@homeserver.lan "cd ~/network-assistant && git pull && docker compose up --build -d"
```

`docker compose up --build -d` rebuilds the image (dashboard + Python deps) and restarts the container. `devices.json` on the host persists across rebuilds via the volume mount — device labels are never lost.

## Out of Scope

- Reverse proxy / clean hostnames per service (deferred — future landing page work)
- CI/CD pipeline (manual deploy is sufficient for a home project)
- Separating test dependencies into `requirements-dev.txt` (not worth the complexity)
- Dev workflow for local iteration (edit mcp_settings.json manually to `localhost:8000` when needed)
