# Network Assistant Dashboard — Design Spec

**Date:** 2026-06-04
**Status:** Approved

## Overview

A React web dashboard served from the existing MCP server that provides real-time monitoring and control of all home network devices. Replaces ad-hoc Claude queries for routine status checks with a persistent, auto-refreshing UI.

**Goal:** Single-URL dashboard (`http://localhost:8000`) that shows network health at a glance and lets the user take common actions (toggle Pi-hole blocking, switch active WAN, label devices, manage port forwards) without needing to ask Claude.

---

## Architecture

### Backend

FastMCP's `@mcp.custom_route` decorator adds REST endpoints to the existing SSE server on port 8000. No new process, no new port.

New file **`src/api.py`** — async handler functions called by the custom routes. Keeps `server.py` clean. Imports the same client classes the MCP tools already use (fresh instance per call, consistent with existing pattern).

New routes added to **`server.py`**:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/snapshot` | WAN health + Pi-hole stats + mesh health + router info — all concurrent via `asyncio.gather`. Used by Overview tab. |
| GET | `/api/wan` | `get_wan_health()` — per-interface latency/packet loss |
| POST | `/api/wan/priority` | `set_wan_priority(primary_wan)` — body: `{"primary_wan": "WAN1"\|"WAN2"\|"auto"}` |
| POST | `/api/wan/compare` | `compare_wan_health()` — on-demand only, warns in response that it briefly disrupts traffic |
| GET | `/api/pihole/stats` | `get_pihole_stats()` |
| GET | `/api/pihole/trends` | `get_query_trends()` |
| GET | `/api/pihole/top-domains` | `get_top_domains(blocked=False)` + `get_top_domains(blocked=True)` — returns both in one response |
| GET | `/api/pihole/system` | `get_pihole_system()` |
| POST | `/api/pihole/blocking` | `set_blocking(enabled)` — body: `{"enabled": true\|false}` |
| GET | `/api/mesh` | `get_mesh_health()` |
| GET | `/api/devices` | `get_network_devices(deep_scan=False)` |
| POST | `/api/devices/scan` | `get_network_devices(deep_scan=True)` — manual trigger |
| POST | `/api/devices/{mac}/label` | `label_device(mac, label)` — body: `{"label": "..."}` |
| DELETE | `/api/devices/{mac}/label` | `remove_device_label(mac)` |
| GET | `/api/upnp` | `get_upnp_status()` + `get_upnp_portmaps()` — combined |
| GET | `/api/ports` | `get_port_forwards()` |
| POST | `/api/ports` | `add_port_forward(...)` — body: `{"name": str, "external_port": int, "internal_ip": str, "internal_port": int, "protocol": "tcp"\|"udp"\|"both"}`; always `dry_run=False` from UI |
| DELETE | `/api/ports/{rule_id}` | `remove_port_forward(rule_id)` |
| GET | `/` | Serve `dashboard/dist/index.html` |
| GET | `/{path:path}` | Serve static assets from `dashboard/dist/`; fall back to `index.html` for unknown paths (SPA routing) |

All endpoints return JSON. Error shape matches existing tool convention: `{"success": false, "error": "...", "suggestion": "..."}`.

### Frontend

React + Vite + TypeScript project in **`dashboard/`** at the project root.

**Dependencies:**
- `shadcn/ui` — Cards, Tabs, Table, Badge, Button, Dialog, Switch, Tooltip
- `recharts` — AreaChart for 24h DNS query trends
- `@tanstack/react-query` — data fetching with auto-refresh intervals
- `lucide-react` — icons (already a shadcn/ui dependency)

**Directory structure:**
```
dashboard/
  src/
    App.tsx               — root: tabs + theme provider
    lib/
      api.ts              — all fetch calls, typed return values
      types.ts            — TypeScript interfaces matching API responses
    components/
      StatCard.tsx         — compact metric card (used in Overview)
      StatusBadge.tsx      — green/red/yellow online indicator
      RefreshButton.tsx    — manual refresh trigger
      ThemeToggle.tsx      — dark/light switch
    pages/
      OverviewPage.tsx     — stat cards + query trends chart
      NetworkPage.tsx      — mesh nodes + device inventory table
      DnsPage.tsx          — Pi-hole stats + top domains + system info
      FirewallPage.tsx     — port forwards + UPnP port maps
  vite.config.ts          — proxy /api/* → http://localhost:8000 in dev
  package.json
```

---

## Tab Contents

### Overview
- **Stat cards (5):** WAN1 status/latency, WAN2 status/latency, Pi-hole block % + toggle button, Mesh node count, Router uptime
- **Query trends chart:** 24h area chart (total queries + blocked overlay), spike hours highlighted in amber
- **Auto-refresh:** 30 seconds (`/api/snapshot`)

### Network
- **Mesh nodes panel:** Each Deco node — nickname, online status, backhaul type (wired/wireless), signal dBm
- **Device inventory table:** IP, hostname/label, vendor, MAC (truncated), label/edit action. Search box to filter. Manual "Scan" button triggers deep scan.
- **Auto-refresh:** 30 seconds for mesh; device table manual only

### DNS
- **Pi-hole stats bar:** Queries today, blocked count, block %, domains on blocklist, blocking toggle
- **Top queried / top blocked:** Side-by-side tables (10 rows each)
- **Pi-hole system:** CPU %, RAM %, uptime
- **Auto-refresh:** 30 seconds for stats and system info; top domains manual

### Firewall
- **Port forwards table:** Name, external port, internal IP:port, protocol. Add rule button opens a Dialog form. Remove button per row (with confirmation).
- **UPnP port maps table:** Description, external port, internal client IP, protocol, TTL. Read-only.
- **Auto-refresh:** Manual only

---

## Data Fetching

TanStack Query manages all fetching. Key intervals:

| Data | Interval |
|------|----------|
| Overview snapshot | 30s |
| Mesh health | 30s |
| Pi-hole stats | 30s |
| Query trends | 5 min |
| Device inventory | Manual |
| Port forwards | Manual |
| UPnP maps | Manual |

The header shows "Updated N seconds ago" using the query's `dataUpdatedAt` timestamp. A global refresh button re-fetches all active queries.

WAN comparison (`/api/wan/compare`) and deep device scan (`/api/devices/scan`) are triggered by explicit user action only. Both show a loading spinner with a warning ("This will briefly affect active connections" for WAN compare).

---

## Error Handling

- Each card/section checks `success` in the API response independently. A failed WAN health call shows an error state in the WAN cards without affecting Pi-hole or mesh cards.
- On network error (fetch fails entirely), TanStack Query retries once after 5 seconds, then shows a stale-data indicator.
- Write operations (toggle blocking, switch WAN, add/remove rules) show a toast notification on success or failure using shadcn/ui's `toast`.

---

## Development Workflow

```bash
# Terminal 1 — MCP + API server
.venv/bin/python -m src.server

# Terminal 2 — Vite dev server (hot reload, proxies /api/* to :8000)
cd dashboard && npm run dev
# → http://localhost:5173

# Build for production (served by MCP server at :8000)
cd dashboard && npm run build
# → dashboard/dist/
```

---

## Testing

No new frontend unit tests — this is a personal dashboard. Backend API handlers call the same client functions covered by the 156 existing tests.

One new smoke test added to `tests/test_server.py`: verify `GET /api/snapshot` returns HTTP 200 with `wan`, `pihole`, `mesh`, and `router` keys present.

---

## Files Changed / Created

**New:**
- `src/api.py` — async API handler functions
- `dashboard/` — full React + Vite project
- `docs/superpowers/specs/2026-06-04-dashboard-design.md` (this file)

**Modified:**
- `src/server.py` — add `@mcp.custom_route` endpoints + static file serving
- `requirements.txt` — no changes needed (no new Python deps)
- `tests/test_server.py` — add snapshot smoke test
- `CLAUDE.md` — update status
