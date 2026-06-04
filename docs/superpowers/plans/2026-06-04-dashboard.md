# Network Assistant Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a React web dashboard to the existing MCP server — served at `http://localhost:8000`, auto-refreshing, with monitoring and control across all 9 network sections.

**Architecture:** REST endpoints added to the existing FastMCP server via `@mcp.custom_route`; no new process or port. A React + Vite + TypeScript project in `dashboard/` fetches from `/api/*` and the built output is served as static files from the same server.

**Tech Stack:** Python (FastMCP custom_route, asyncio.to_thread), React 18, Vite, TypeScript, shadcn/ui, Recharts, TanStack Query

---

## File Map

**New (backend):**
- `src/api.py` — async handler functions (one per API endpoint group); called by server.py routes
- `tests/test_api.py` — snapshot endpoint smoke test

**Modified (backend):**
- `src/server.py` — import api.py, register `@mcp.custom_route` handlers, add static file catch-all
- `.gitignore` — add `dashboard/node_modules/` and `dashboard/dist/`

**New (frontend, all inside `dashboard/`):**
- `package.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.app.json`, `index.html` — project config
- `tailwind.config.js`, `postcss.config.js` — Tailwind config
- `components.json` — shadcn/ui config
- `src/main.tsx` — React entry, QueryClientProvider
- `src/App.tsx` — root: sticky header, Tabs nav, theme toggle
- `src/lib/types.ts` — TypeScript interfaces for all API responses
- `src/lib/api.ts` — typed fetch wrappers for every endpoint
- `src/lib/utils.ts` — append `formatUptime()` helper (file already created by shadcn init with `cn`)
- `src/components/StatCard.tsx` — compact metric card with optional action slot
- `src/components/StatusBadge.tsx` — green/red online indicator badge
- `src/components/ThemeToggle.tsx` — dark/light toggle button
- `src/components/RefreshButton.tsx` — global refresh with spin animation
- `src/pages/OverviewPage.tsx` — 5 stat cards + 24h query trends chart
- `src/pages/NetworkPage.tsx` — Deco mesh nodes + device inventory table
- `src/pages/DnsPage.tsx` — Pi-hole stats bar + top domains + system info
- `src/pages/FirewallPage.tsx` — port forwards table + UPnP port maps table

---

## Task 1: Write failing snapshot test

**Files:**
- Create: `tests/test_api.py`

- [ ] **Step 1: Create the test file**

```python
# tests/test_api.py
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
import src.server as server_module


def _mock_cfg():
    cfg = MagicMock()
    cfg.er605 = MagicMock(host="192.168.0.1", username="admin", password="secret")
    cfg.pihole = MagicMock(host="192.168.0.10", api_token="testtoken")
    cfg.deco = MagicMock(host="192.168.0.100", password="testpass")
    return cfg


def test_snapshot_returns_expected_keys():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.WANHealthClient") as mock_wan, \
         patch("src.api.PiholeClient") as mock_pihole, \
         patch("src.api.DecoClient") as mock_deco, \
         patch("src.api.ER605Client") as mock_er605:

        mock_wan.return_value.get_wan_health.return_value = {"success": True, "wan1": {}}
        mock_pihole.return_value.get_pihole_stats.return_value = {"success": True}
        mock_deco.return_value.get_mesh_health.return_value = {"success": True, "nodes": []}
        mock_er605.return_value.get_router_info.return_value = {"success": True}

        client = TestClient(server_module.mcp.sse_app())
        resp = client.get("/api/snapshot")

    assert resp.status_code == 200
    data = resp.json()
    assert "wan" in data
    assert "pihole" in data
    assert "mesh" in data
    assert "router" in data
```

- [ ] **Step 2: Run the test — confirm it fails**

```bash
.venv/bin/pytest tests/test_api.py -v
```
Expected: `FAILED` — `ModuleNotFoundError: No module named 'src.api'` (or 404 if routes not yet wired)

- [ ] **Step 3: Commit**

```bash
git add tests/test_api.py
git commit -m "test: add snapshot API smoke test (red)"
```

---

## Task 2: Implement `src/api.py`

**Files:**
- Create: `src/api.py`

- [ ] **Step 1: Create the file**

```python
# src/api.py
import asyncio
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from src.config import Config
from src.tools.deco import DecoClient
from src.tools.devices import DeviceInventory
from src.tools.er605 import ER605Client
from src.tools.pihole import PiholeClient
from src.tools.upnp import get_upnp_portmaps, get_upnp_status
from src.tools.wan_health import WANHealthClient

_LABELS_PATH = Path(__file__).parent.parent / "devices.json"
_DIST = Path(__file__).parent.parent / "dashboard" / "dist"


async def snapshot(cfg: Config) -> dict:
    wan, pihole, mesh, router = await asyncio.gather(
        asyncio.to_thread(WANHealthClient(**vars(cfg.er605)).get_wan_health),
        asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_pihole_stats),
        asyncio.to_thread(DecoClient(**vars(cfg.deco)).get_mesh_health),
        asyncio.to_thread(ER605Client(**vars(cfg.er605)).get_router_info),
        return_exceptions=True,
    )
    return {
        "wan": wan if not isinstance(wan, Exception) else {"success": False, "error": str(wan)},
        "pihole": pihole if not isinstance(pihole, Exception) else {"success": False, "error": str(pihole)},
        "mesh": mesh if not isinstance(mesh, Exception) else {"success": False, "error": str(mesh)},
        "router": router if not isinstance(router, Exception) else {"success": False, "error": str(router)},
    }


async def wan_health(cfg: Config) -> dict:
    return await asyncio.to_thread(WANHealthClient(**vars(cfg.er605)).get_wan_health)


async def wan_compare(cfg: Config) -> dict:
    return await asyncio.to_thread(WANHealthClient(**vars(cfg.er605)).compare_wan_health)


async def set_wan_priority(cfg: Config, primary_wan: str) -> dict:
    return await asyncio.to_thread(ER605Client(**vars(cfg.er605)).set_wan_priority, primary_wan)


async def pihole_stats(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_pihole_stats)


async def pihole_trends(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_query_trends)


async def pihole_top_domains(cfg: Config) -> dict:
    queried, blocked = await asyncio.gather(
        asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_top_domains, False),
        asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_top_domains, True),
    )
    return {"queried": queried, "blocked": blocked}


async def pihole_system(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_pihole_system)


async def set_pihole_blocking(cfg: Config, enabled: bool) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).set_blocking, enabled)


async def mesh_health(cfg: Config) -> dict:
    return await asyncio.to_thread(DecoClient(**vars(cfg.deco)).get_mesh_health)


async def get_devices(cfg: Config, deep_scan: bool = False) -> dict:
    inventory = DeviceInventory(labels_path=_LABELS_PATH, cfg=cfg)
    return await asyncio.to_thread(inventory.get_network_devices, deep_scan)


async def do_label_device(cfg: Config, mac: str, label: str) -> dict:
    inventory = DeviceInventory(labels_path=_LABELS_PATH, cfg=cfg)
    return await asyncio.to_thread(inventory.label_device, mac, label)


async def do_remove_label(cfg: Config, mac: str) -> dict:
    inventory = DeviceInventory(labels_path=_LABELS_PATH, cfg=cfg)
    return await asyncio.to_thread(inventory.remove_device_label, mac)


async def upnp() -> dict:
    status, portmaps = await asyncio.gather(
        asyncio.to_thread(get_upnp_status),
        asyncio.to_thread(get_upnp_portmaps),
    )
    return {"status": status, "portmaps": portmaps}


async def get_port_forwards(cfg: Config) -> dict:
    return await asyncio.to_thread(ER605Client(**vars(cfg.er605)).get_port_forwards)


async def do_add_port_forward(
    cfg: Config,
    name: str,
    external_port: int,
    internal_ip: str,
    internal_port: int,
    protocol: str,
) -> dict:
    return await asyncio.to_thread(
        ER605Client(**vars(cfg.er605)).add_port_forward,
        name, external_port, internal_ip, internal_port,
        protocol=protocol, dry_run=False,
    )


async def do_remove_port_forward(cfg: Config, rule_id: str) -> dict:
    return await asyncio.to_thread(ER605Client(**vars(cfg.er605)).remove_port_forward, rule_id)


async def serve_static(request: Request) -> Response:
    path = request.path_params.get("path", "") or "index.html"
    if not _DIST.exists():
        return JSONResponse(
            {"error": "Dashboard not built. Run: cd dashboard && npm run build"},
            status_code=503,
        )
    file_path = _DIST / path
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    index = _DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"error": "Not found"}, status_code=404)
```

- [ ] **Step 2: Commit**

```bash
git add src/api.py
git commit -m "feat: add REST API handler functions (src/api.py)"
```

---

## Task 3: Wire routes in `server.py` — verify test passes

**Files:**
- Modify: `src/server.py`

- [ ] **Step 1: Add imports at the top of `server.py`** (after existing imports)

```python
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from src import api as api
```

- [ ] **Step 2: Add the `_NO_CONFIG` constant** (already exists in server.py — skip if present, it's already there)

It already exists as `_NO_CONFIG = {"success": False, ...}` — no change needed.

- [ ] **Step 3: Append all custom routes to the bottom of `server.py`** (before `if __name__ == "__main__":`)

```python
# ── REST API routes ──────────────────────────────────────────────────────────

@mcp.custom_route("/api/snapshot", methods=["GET"])
async def _api_snapshot(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.snapshot(_cfg))


@mcp.custom_route("/api/wan", methods=["GET"])
async def _api_wan(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.wan_health(_cfg))


@mcp.custom_route("/api/wan/priority", methods=["POST"])
async def _api_wan_priority(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    body = await request.json()
    return JSONResponse(await api.set_wan_priority(_cfg, body.get("primary_wan", "auto")))


@mcp.custom_route("/api/wan/compare", methods=["POST"])
async def _api_wan_compare(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.wan_compare(_cfg))


@mcp.custom_route("/api/pihole/stats", methods=["GET"])
async def _api_pihole_stats(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.pihole_stats(_cfg))


@mcp.custom_route("/api/pihole/trends", methods=["GET"])
async def _api_pihole_trends(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.pihole_trends(_cfg))


@mcp.custom_route("/api/pihole/top-domains", methods=["GET"])
async def _api_pihole_top_domains(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.pihole_top_domains(_cfg))


@mcp.custom_route("/api/pihole/system", methods=["GET"])
async def _api_pihole_system(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.pihole_system(_cfg))


@mcp.custom_route("/api/pihole/blocking", methods=["POST"])
async def _api_pihole_blocking(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    body = await request.json()
    return JSONResponse(await api.set_pihole_blocking(_cfg, bool(body.get("enabled", True))))


@mcp.custom_route("/api/mesh", methods=["GET"])
async def _api_mesh(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.mesh_health(_cfg))


@mcp.custom_route("/api/devices", methods=["GET"])
async def _api_devices(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.get_devices(_cfg))


@mcp.custom_route("/api/devices/scan", methods=["POST"])
async def _api_devices_scan(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.get_devices(_cfg, deep_scan=True))


@mcp.custom_route("/api/devices/{mac}/label", methods=["POST", "DELETE"])
async def _api_device_label(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    mac = request.path_params["mac"]
    if request.method == "DELETE":
        return JSONResponse(await api.do_remove_label(_cfg, mac))
    body = await request.json()
    return JSONResponse(await api.do_label_device(_cfg, mac, body.get("label", "")))


@mcp.custom_route("/api/upnp", methods=["GET"])
async def _api_upnp(request: Request) -> JSONResponse:
    return JSONResponse(await api.upnp())


@mcp.custom_route("/api/ports", methods=["GET", "POST"])
async def _api_ports(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    if request.method == "POST":
        body = await request.json()
        return JSONResponse(await api.do_add_port_forward(
            _cfg,
            body["name"],
            int(body["external_port"]),
            body["internal_ip"],
            int(body["internal_port"]),
            body.get("protocol", "tcp"),
        ))
    return JSONResponse(await api.get_port_forwards(_cfg))


@mcp.custom_route("/api/ports/{rule_id}", methods=["DELETE"])
async def _api_ports_remove(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.do_remove_port_forward(_cfg, request.path_params["rule_id"]))


# Must be last — catch-all for React SPA
@mcp.custom_route("/{path:path}", methods=["GET"])
async def _serve_static(request: Request) -> Response:
    return await api.serve_static(request)
```

- [ ] **Step 4: Run the snapshot test — it should pass now**

```bash
.venv/bin/pytest tests/test_api.py tests/test_server.py -v
```
Expected: all tests pass. If `test_snapshot_returns_expected_keys` still fails, check that `src.server._cfg` patch and mock client patches line up with the imports in `src/api.py`.

- [ ] **Step 5: Run the full test suite — nothing broken**

```bash
.venv/bin/pytest -v
```
Expected: 157+ tests, all passing.

- [ ] **Step 6: Commit**

```bash
git add src/server.py
git commit -m "feat: wire REST API routes and static file serving in server.py"
```

---

## Task 4: Scaffold and configure the React project

**Files:**
- Create: `dashboard/` (entire directory via npm commands)
- Modify: `.gitignore`

- [ ] **Step 1: Add dashboard build artifacts to `.gitignore`**

Append these two lines to `.gitignore`:
```
dashboard/node_modules/
dashboard/dist/
```

- [ ] **Step 2: Scaffold the Vite + React + TypeScript project**

```bash
npm create vite@latest dashboard -- --template react-ts
```

- [ ] **Step 3: Install runtime dependencies**

```bash
cd dashboard && npm install
npm install @tanstack/react-query recharts
npm install sonner
```

- [ ] **Step 4: Install and configure Tailwind CSS**

```bash
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

- [ ] **Step 5: Update `tailwind.config.js`** to scan all source files and enable dark mode

```js
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```

- [ ] **Step 6: Replace `dashboard/src/index.css`** with Tailwind directives (shadcn/ui init will add CSS variables in the next step, but start with the base directives)

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 7: Initialize shadcn/ui** (interactive — answer as shown)

```bash
npx shadcn@latest init
```

Answer the prompts:
- Style: **Default**
- Base color: **Slate**
- CSS variables: **yes**

- [ ] **Step 8: Add all required shadcn/ui components**

```bash
npx shadcn@latest add card tabs table badge button dialog switch input label sonner tooltip
```

- [ ] **Step 9: Replace `dashboard/vite.config.ts`** with the proxy configuration

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 10: Install the `path` types needed for vite.config.ts**

```bash
npm install -D @types/node
```

- [ ] **Step 11: Verify the dev server starts**

```bash
npm run dev
```
Expected: Vite prints `Local: http://localhost:5173/` with no errors. Stop with Ctrl+C.

- [ ] **Step 12: Commit**

```bash
cd .. && git add .gitignore dashboard/
git commit -m "feat: scaffold React + Vite dashboard project with shadcn/ui"
```

---

## Task 5: Create `lib/types.ts`, `lib/api.ts`, and utility additions

**Files:**
- Create: `dashboard/src/lib/types.ts`
- Create: `dashboard/src/lib/api.ts`
- Modify: `dashboard/src/lib/utils.ts` (append formatUptime)

- [ ] **Step 1: Create `dashboard/src/lib/types.ts`**

```typescript
// All API response shapes — field names match Python tool return values exactly.

export interface WANInterface {
  link: 'up' | 'down'
  ip: string | null
  gateway: string | null
}

export interface WANProbe {
  latency_ms: number | null
  packet_loss_pct: number
}

export interface WANHealth {
  success: boolean
  active_wan: 'WAN1' | 'WAN2' | null
  wan1: WANInterface | null
  wan2: WANInterface | null
  probe: WANProbe | null
  degraded: boolean
  error?: string
}

export interface PiholeStats {
  success: boolean
  queries_today: number
  blocked_today: number
  block_pct: number
  domains_blocked: number
  enabled: boolean
  error?: string
}

export interface MeshNode {
  mac: string | null
  ip: string | null
  nickname: string | null
  is_primary: boolean
  mesh_status: string
  inet_status: string | null
  inet_error: string | null
  backhaul: string | null
  signal_level_dbm: number | null
}

export interface MeshHealth {
  success: boolean
  nodes: MeshNode[]
  node_count: number
  error?: string
}

export interface RouterInfo {
  success: boolean
  model: string | null
  firmware: string | null
  uptime_seconds: number | null
  cpu_percent: number | null
  mem_percent: number | null
  error?: string
}

export interface Snapshot {
  wan: WANHealth
  pihole: PiholeStats
  mesh: MeshHealth
  router: RouterInfo
}

export interface TrendHour {
  hour: string
  total: number
  blocked: number
  block_pct: number
}

export interface QueryTrends {
  success: boolean
  hours: TrendHour[]
  summary: {
    total_24h: number
    blocked_24h: number
    block_pct_24h: number
    avg_per_hour: number
    spike_hours: number[]
  }
  error?: string
}

export interface DomainEntry {
  domain: string
  count: number
}

export interface TopDomainsResult {
  queried: { success: boolean; domains: DomainEntry[]; blocked_filter: boolean; error?: string }
  blocked: { success: boolean; domains: DomainEntry[]; blocked_filter: boolean; error?: string }
}

export interface PiholeSystem {
  success: boolean
  hostname: string
  uptime_seconds: number
  cpu_load_1m: number
  cpu_load_5m: number
  cpu_load_15m: number
  ram_total_mb: number
  ram_used_mb: number
  ram_free_mb: number
  error?: string
}

export interface Device {
  ip: string
  mac: string | null
  label: string | null
  hostname: string | null
  vendor: string | null
  deco_node: string | null
  deco_signal_dbm: number | null
  connection_type: string | null
  pihole_queries_today: number | null
  pihole_last_seen: string | null
}

export interface DeviceList {
  success: boolean
  deep_scan: boolean
  device_count: number
  devices: Device[]
  error?: string
}

export interface UPnPMapping {
  external_port: number
  protocol: string
  internal_host: string
  internal_port: number
  description: string
  enabled: boolean
  remote_host: string
  lease_seconds: number
}

export interface UPnPResult {
  status: { success: boolean; available?: boolean; external_ip?: string; connected?: boolean; error?: string }
  portmaps: { success: boolean; available?: boolean; count?: number; mappings: UPnPMapping[]; error?: string }
}

export interface PortForward {
  id: string | null
  name: string
  external_port: number
  internal_ip: string
  internal_port: number
  protocol: string
}

export interface PortForwards {
  success: boolean
  rules: PortForward[]
  error?: string
}
```

- [ ] **Step 2: Create `dashboard/src/lib/api.ts`**

```typescript
import type {
  Snapshot, WANHealth, QueryTrends, TopDomainsResult, PiholeStats,
  PiholeSystem, MeshHealth, DeviceList, UPnPResult, PortForwards,
} from './types'

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

async function del<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`, { method: 'DELETE' })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

export const api = {
  getSnapshot: () => get<Snapshot>('/snapshot'),
  getWanHealth: () => get<WANHealth>('/wan'),
  compareWan: () => post<unknown>('/wan/compare'),
  setWanPriority: (primary_wan: string) => post<unknown>('/wan/priority', { primary_wan }),

  getPiholeStats: () => get<PiholeStats>('/pihole/stats'),
  getPiholeTrends: () => get<QueryTrends>('/pihole/trends'),
  getPiholeTopDomains: () => get<TopDomainsResult>('/pihole/top-domains'),
  getPiholeSystem: () => get<PiholeSystem>('/pihole/system'),
  setPiholeBlocking: (enabled: boolean) => post<unknown>('/pihole/blocking', { enabled }),

  getMeshHealth: () => get<MeshHealth>('/mesh'),

  getDevices: () => get<DeviceList>('/devices'),
  scanDevices: () => post<DeviceList>('/devices/scan'),
  labelDevice: (mac: string, label: string) =>
    post<unknown>(`/devices/${encodeURIComponent(mac)}/label`, { label }),
  removeDeviceLabel: (mac: string) =>
    del<unknown>(`/devices/${encodeURIComponent(mac)}/label`),

  getUpnp: () => get<UPnPResult>('/upnp'),

  getPortForwards: () => get<PortForwards>('/ports'),
  addPortForward: (data: {
    name: string; external_port: number; internal_ip: string;
    internal_port: number; protocol: string
  }) => post<unknown>('/ports', data),
  removePortForward: (ruleId: string) =>
    del<unknown>(`/ports/${encodeURIComponent(ruleId)}`),
}
```

- [ ] **Step 3: Append `formatUptime` to `dashboard/src/lib/utils.ts`**

The file was created by shadcn/ui init with a `cn` function. Append:

```typescript
export function formatUptime(seconds?: number | null): string {
  if (!seconds) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  return d > 0 ? `${d}d ${h}h` : `${h}h`
}
```

- [ ] **Step 4: Commit**

```bash
cd .. && git add dashboard/src/lib/
git commit -m "feat: add TypeScript types and API client for dashboard"
```

---

## Task 6: Shared components and App shell

**Files:**
- Create: `dashboard/src/components/StatCard.tsx`
- Create: `dashboard/src/components/StatusBadge.tsx`
- Create: `dashboard/src/components/ThemeToggle.tsx`
- Create: `dashboard/src/components/RefreshButton.tsx`
- Create: `dashboard/src/App.tsx` (replace generated)
- Modify: `dashboard/src/main.tsx` (replace generated)

- [ ] **Step 1: Create `dashboard/src/components/StatCard.tsx`**

```tsx
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface StatCardProps {
  title: string
  value: React.ReactNode
  subtitle?: string
  action?: React.ReactNode
}

export function StatCard({ title, value, subtitle, action }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-xl font-bold">{value}</div>
        {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
        {action && <div className="mt-3">{action}</div>}
      </CardContent>
    </Card>
  )
}
```

- [ ] **Step 2: Create `dashboard/src/components/StatusBadge.tsx`**

```tsx
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

interface StatusBadgeProps {
  online: boolean
  label?: string
}

export function StatusBadge({ online, label }: StatusBadgeProps) {
  return (
    <Badge className={cn(online ? 'bg-green-600 hover:bg-green-600' : 'bg-red-600 hover:bg-red-600', 'text-white')}>
      ● {label ?? (online ? 'Online' : 'Offline')}
    </Badge>
  )
}
```

- [ ] **Step 3: Create `dashboard/src/components/ThemeToggle.tsx`**

```tsx
import { Sun, Moon } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface ThemeToggleProps {
  theme: 'dark' | 'light'
  onToggle: () => void
}

export function ThemeToggle({ theme, onToggle }: ThemeToggleProps) {
  return (
    <Button variant="ghost" size="icon" onClick={onToggle} title="Toggle theme">
      {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  )
}
```

- [ ] **Step 4: Create `dashboard/src/components/RefreshButton.tsx`**

```tsx
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface RefreshButtonProps {
  onRefresh: () => void
  isRefreshing?: boolean
}

export function RefreshButton({ onRefresh, isRefreshing }: RefreshButtonProps) {
  return (
    <Button variant="ghost" size="icon" onClick={onRefresh} title="Refresh all">
      <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
    </Button>
  )
}
```

- [ ] **Step 5: Replace `dashboard/src/main.tsx`**

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App.tsx'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      retryDelay: 5000,
      staleTime: 0,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
```

- [ ] **Step 6: Replace `dashboard/src/App.tsx`**

```tsx
import { useState, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Toaster } from '@/components/ui/sonner'
import { ThemeToggle } from '@/components/ThemeToggle'
import { RefreshButton } from '@/components/RefreshButton'
import OverviewPage from '@/pages/OverviewPage'
import NetworkPage from '@/pages/NetworkPage'
import DnsPage from '@/pages/DnsPage'
import FirewallPage from '@/pages/FirewallPage'

export default function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (localStorage.getItem('theme') as 'dark' | 'light') || 'dark'
  )
  const queryClient = useQueryClient()

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('theme', theme)
  }, [theme])

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Toaster />
      <Tabs defaultValue="overview">
        <header className="sticky top-0 z-10 border-b border-border bg-background px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <span className="font-bold text-base">🛜 Network Assistant</span>
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="network">Network</TabsTrigger>
              <TabsTrigger value="dns">DNS</TabsTrigger>
              <TabsTrigger value="firewall">Firewall</TabsTrigger>
            </TabsList>
          </div>
          <div className="flex items-center gap-1">
            <RefreshButton onRefresh={() => queryClient.invalidateQueries()} />
            <ThemeToggle
              theme={theme}
              onToggle={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
            />
          </div>
        </header>
        <main className="p-6">
          <TabsContent value="overview"><OverviewPage /></TabsContent>
          <TabsContent value="network"><NetworkPage /></TabsContent>
          <TabsContent value="dns"><DnsPage /></TabsContent>
          <TabsContent value="firewall"><FirewallPage /></TabsContent>
        </main>
      </Tabs>
    </div>
  )
}
```

- [ ] **Step 7: Create stub page files** so the app compiles before pages are implemented

Create `dashboard/src/pages/OverviewPage.tsx`:
```tsx
export default function OverviewPage() { return <div>Overview</div> }
```

Create `dashboard/src/pages/NetworkPage.tsx`:
```tsx
export default function NetworkPage() { return <div>Network</div> }
```

Create `dashboard/src/pages/DnsPage.tsx`:
```tsx
export default function DnsPage() { return <div>DNS</div> }
```

Create `dashboard/src/pages/FirewallPage.tsx`:
```tsx
export default function FirewallPage() { return <div>Firewall</div> }
```

- [ ] **Step 8: Start the dev server and verify the shell loads**

```bash
cd dashboard && npm run dev
```
Open http://localhost:5173 — you should see the header with 🛜, four tabs, and stub page text. Theme toggle and tab switching should work. Stop with Ctrl+C.

- [ ] **Step 9: Commit**

```bash
cd .. && git add dashboard/src/
git commit -m "feat: add app shell, shared components, stub pages"
```

---

## Task 7: OverviewPage

**Files:**
- Modify: `dashboard/src/pages/OverviewPage.tsx`

- [ ] **Step 1: Replace `dashboard/src/pages/OverviewPage.tsx`**

```tsx
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { api } from '@/lib/api'
import { formatUptime } from '@/lib/utils'
import { StatCard } from '@/components/StatCard'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'

export default function OverviewPage() {
  const queryClient = useQueryClient()

  const { data: snap, isLoading } = useQuery({
    queryKey: ['snapshot'],
    queryFn: api.getSnapshot,
    refetchInterval: 30_000,
  })

  const { data: trends } = useQuery({
    queryKey: ['trends'],
    queryFn: api.getPiholeTrends,
    refetchInterval: 300_000,
  })

  const handleToggleBlocking = async () => {
    if (!snap?.pihole?.success) return
    try {
      await api.setPiholeBlocking(!snap.pihole.enabled)
      queryClient.invalidateQueries({ queryKey: ['snapshot'] })
      toast.success(snap.pihole.enabled ? 'Pi-hole blocking disabled' : 'Pi-hole blocking enabled')
    } catch {
      toast.error('Failed to toggle Pi-hole blocking')
    }
  }

  const handleSwitchWan = async (wan: string) => {
    try {
      await api.setWanPriority(wan)
      queryClient.invalidateQueries({ queryKey: ['snapshot'] })
      toast.success(`Switched active WAN to ${wan}`)
    } catch {
      toast.error('Failed to switch WAN')
    }
  }

  if (isLoading) {
    return <div className="text-muted-foreground text-sm">Loading...</div>
  }

  const wan1Up = snap?.wan?.wan1?.link === 'up'
  const wan2Up = snap?.wan?.wan2?.link === 'up'
  const activeWan = snap?.wan?.active_wan
  const probe = snap?.wan?.probe
  const pihole = snap?.pihole
  const mesh = snap?.mesh
  const router = snap?.router

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard
          title="WAN1"
          value={<StatusBadge online={wan1Up} />}
          subtitle={probe && wan1Up ? `${probe.latency_ms?.toFixed(0) ?? '—'}ms · ${probe.packet_loss_pct}% loss` : undefined}
          action={activeWan !== 'WAN1' && wan1Up ? (
            <Button size="sm" variant="outline" onClick={() => handleSwitchWan('WAN1')}>
              Set Active
            </Button>
          ) : activeWan === 'WAN1' ? (
            <Badge variant="secondary">Active</Badge>
          ) : undefined}
        />
        <StatCard
          title="WAN2"
          value={<StatusBadge online={wan2Up} />}
          subtitle={probe && wan2Up ? `${probe.latency_ms?.toFixed(0) ?? '—'}ms · ${probe.packet_loss_pct}% loss` : undefined}
          action={activeWan !== 'WAN2' && wan2Up ? (
            <Button size="sm" variant="outline" onClick={() => handleSwitchWan('WAN2')}>
              Set Active
            </Button>
          ) : activeWan === 'WAN2' ? (
            <Badge variant="secondary">Active</Badge>
          ) : undefined}
        />
        <StatCard
          title="Pi-hole"
          value={pihole?.success ? `${pihole.block_pct}% blocked` : '—'}
          subtitle={pihole?.success ? `${pihole.queries_today.toLocaleString()} queries today` : pihole?.error}
          action={pihole?.success ? (
            <div className="flex items-center gap-2">
              <Switch
                checked={pihole.enabled}
                onCheckedChange={handleToggleBlocking}
              />
              <span className="text-xs text-muted-foreground">
                {pihole.enabled ? 'Blocking on' : 'Blocking off'}
              </span>
            </div>
          ) : undefined}
        />
        <StatCard
          title="Mesh"
          value={mesh?.success ? `${mesh.node_count} / ${mesh.nodes.length} online` : '—'}
          subtitle={mesh?.success ? (mesh.node_count === mesh.nodes.length ? 'All nodes healthy' : 'Some nodes offline') : mesh?.error}
        />
        <StatCard
          title="Router"
          value={router?.success ? (router.model ?? 'ER605') : '—'}
          subtitle={router?.success ? `Uptime: ${formatUptime(router.uptime_seconds)}` : router?.error}
        />
      </div>

      {/* Query trends chart */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium text-muted-foreground mb-4">
          DNS Query Trends — Last 24 Hours
        </h3>
        {trends?.success && trends.hours.length > 0 ? (
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={trends.hours} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="gradTotal" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradBlocked" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f87171" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#f87171" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="hour"
                tickFormatter={(v) => `${new Date(v).getHours()}h`}
                tick={{ fontSize: 10 }}
                interval="preserveStartEnd"
              />
              <YAxis tick={{ fontSize: 10 }} width={40} />
              <Tooltip
                formatter={(v: number, name: string) => [v.toLocaleString(), name]}
                labelFormatter={(l) => new Date(l).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              />
              <Area type="monotone" dataKey="total" stroke="#6366f1" fill="url(#gradTotal)" name="Total" />
              <Area type="monotone" dataKey="blocked" stroke="#f87171" fill="url(#gradBlocked)" name="Blocked" />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-40 flex items-center justify-center text-muted-foreground text-sm">
            {trends?.error ?? 'No trend data available'}
          </div>
        )}
        {trends?.summary && (
          <div className="flex gap-4 mt-2 text-xs text-muted-foreground">
            <span>Total 24h: <strong>{trends.summary.total_24h.toLocaleString()}</strong></span>
            <span>Blocked: <strong>{trends.summary.blocked_24h.toLocaleString()} ({trends.summary.block_pct_24h}%)</strong></span>
            {trends.summary.spike_hours.length > 0 && (
              <span className="text-amber-500">Spikes at: {trends.summary.spike_hours.map(h => `${h}h`).join(', ')}</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser** (MCP server must be running)

```bash
# Terminal 1 (already running): .venv/bin/python -m src.server
cd dashboard && npm run dev
```
Open http://localhost:5173 → Overview tab. Stat cards should show real data or error states. Chart should render if Pi-hole is reachable.

- [ ] **Step 3: Commit**

```bash
cd .. && git add dashboard/src/pages/OverviewPage.tsx
git commit -m "feat: implement OverviewPage with stat cards and query trends chart"
```

---

## Task 8: NetworkPage

**Files:**
- Modify: `dashboard/src/pages/NetworkPage.tsx`

- [ ] **Step 1: Replace `dashboard/src/pages/NetworkPage.tsx`**

```tsx
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { StatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import type { Device } from '@/lib/types'

function LabelDialog({ device, onLabeled }: { device: Device; onLabeled: () => void }) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(device.label ?? '')

  const handleSave = async () => {
    try {
      if (value.trim()) {
        await api.labelDevice(device.mac ?? device.ip, value.trim())
        toast.success(`Labeled ${device.ip}`)
      } else {
        await api.removeDeviceLabel(device.mac ?? device.ip)
        toast.success('Label removed')
      }
      onLabeled()
      setOpen(false)
    } catch {
      toast.error('Failed to update label')
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs">
          {device.label ? 'Edit' : 'Label'}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Label device — {device.ip}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div className="space-y-1">
            <Label>Label (leave blank to remove)</Label>
            <Input
              value={value}
              onChange={e => setValue(e.target.value)}
              placeholder="e.g. Xbox Series X"
              onKeyDown={e => e.key === 'Enter' && handleSave()}
            />
          </div>
          <Button onClick={handleSave} className="w-full">Save</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default function NetworkPage() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [scanning, setScanning] = useState(false)

  const { data: mesh, isLoading: meshLoading } = useQuery({
    queryKey: ['mesh'],
    queryFn: api.getMeshHealth,
    refetchInterval: 30_000,
  })

  const { data: deviceData, isLoading: devicesLoading, refetch: refetchDevices } = useQuery({
    queryKey: ['devices'],
    queryFn: api.getDevices,
  })

  const handleDeepScan = async () => {
    setScanning(true)
    try {
      await api.scanDevices()
      await refetchDevices()
      toast.success('Deep scan complete')
    } catch {
      toast.error('Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const filteredDevices = (deviceData?.devices ?? []).filter(d => {
    const q = search.toLowerCase()
    return (
      d.ip.includes(q) ||
      (d.hostname ?? '').toLowerCase().includes(q) ||
      (d.label ?? '').toLowerCase().includes(q) ||
      (d.vendor ?? '').toLowerCase().includes(q)
    )
  })

  return (
    <div className="space-y-6">
      {/* Mesh nodes */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium mb-3">Deco Mesh Nodes</h3>
        {meshLoading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : mesh?.success ? (
          <div className="space-y-2">
            {mesh.nodes.map((node, i) => (
              <div key={i} className="flex items-center gap-3 text-sm">
                <StatusBadge online={node.mesh_status === 'connected'} />
                <span className="font-medium">{node.nickname ?? `Node ${i + 1}`}</span>
                {node.is_primary && <Badge variant="secondary">Primary</Badge>}
                <span className="text-muted-foreground text-xs">
                  {node.backhaul ?? 'unknown backhaul'}
                  {node.signal_level_dbm != null && ` · ${node.signal_level_dbm} dBm`}
                </span>
                {node.ip && <span className="text-muted-foreground text-xs ml-auto">{node.ip}</span>}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">{mesh?.error ?? 'Could not reach Deco'}</div>
        )}
      </div>

      {/* Device inventory */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">
            Device Inventory
            {deviceData?.device_count != null && (
              <span className="text-muted-foreground font-normal ml-2">
                · {deviceData.device_count} devices
              </span>
            )}
          </h3>
          <div className="flex items-center gap-2">
            <Input
              placeholder="Search..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="h-7 w-48 text-xs"
            />
            <Button
              size="sm"
              variant="outline"
              onClick={handleDeepScan}
              disabled={scanning}
              className="h-7 text-xs"
            >
              {scanning ? 'Scanning...' : '↻ Scan'}
            </Button>
          </div>
        </div>
        {devicesLoading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : deviceData?.success ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">IP</TableHead>
                <TableHead className="text-xs">Hostname / Label</TableHead>
                <TableHead className="text-xs">Vendor</TableHead>
                <TableHead className="text-xs">MAC</TableHead>
                <TableHead className="text-xs"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredDevices.map((device) => (
                <TableRow key={device.ip}>
                  <TableCell className="text-xs font-mono">{device.ip}</TableCell>
                  <TableCell className="text-xs">
                    <span>{device.label ?? device.hostname ?? '—'}</span>
                    {device.label && device.hostname && (
                      <span className="text-muted-foreground ml-1">({device.hostname})</span>
                    )}
                    {device.deco_node && (
                      <Badge variant="outline" className="ml-1 text-xs">Deco</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{device.vendor ?? '—'}</TableCell>
                  <TableCell className="text-xs font-mono text-muted-foreground">
                    {device.mac ? device.mac.slice(0, 8) + '…' : '—'}
                  </TableCell>
                  <TableCell>
                    <LabelDialog
                      device={device}
                      onLabeled={() => queryClient.invalidateQueries({ queryKey: ['devices'] })}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="text-sm text-muted-foreground">{deviceData?.error ?? 'Could not load devices'}</div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser** — Network tab should show Deco nodes and device table with label/edit buttons.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/NetworkPage.tsx
git commit -m "feat: implement NetworkPage with mesh nodes and device inventory"
```

---

## Task 9: DnsPage

**Files:**
- Modify: `dashboard/src/pages/DnsPage.tsx`

- [ ] **Step 1: Replace `dashboard/src/pages/DnsPage.tsx`**

```tsx
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { formatUptime } from '@/lib/utils'
import { Switch } from '@/components/ui/switch'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'

export default function DnsPage() {
  const queryClient = useQueryClient()

  const { data: stats } = useQuery({
    queryKey: ['pihole-stats'],
    queryFn: api.getPiholeStats,
    refetchInterval: 30_000,
  })

  const { data: system } = useQuery({
    queryKey: ['pihole-system'],
    queryFn: api.getPiholeSystem,
    refetchInterval: 30_000,
  })

  const { data: topDomains, refetch: refetchTop, isLoading: topLoading } = useQuery({
    queryKey: ['top-domains'],
    queryFn: api.getPiholeTopDomains,
  })

  const handleToggleBlocking = async () => {
    if (!stats?.success) return
    try {
      await api.setPiholeBlocking(!stats.enabled)
      queryClient.invalidateQueries({ queryKey: ['pihole-stats'] })
      queryClient.invalidateQueries({ queryKey: ['snapshot'] })
      toast.success(stats.enabled ? 'Blocking disabled' : 'Blocking enabled')
    } catch {
      toast.error('Failed to toggle Pi-hole blocking')
    }
  }

  const ramPct = system?.success && system.ram_total_mb
    ? Math.round((system.ram_used_mb / system.ram_total_mb) * 100)
    : null

  return (
    <div className="space-y-6">
      {/* Pi-hole stats bar */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Queries Today</div>
          <div className="text-2xl font-bold">{stats?.queries_today?.toLocaleString() ?? '—'}</div>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Blocked</div>
          <div className="text-2xl font-bold text-violet-500">{stats?.block_pct ?? '—'}%</div>
          <div className="text-xs text-muted-foreground">{stats?.blocked_today?.toLocaleString()} queries</div>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Blocklist</div>
          <div className="text-2xl font-bold">{stats?.domains_blocked?.toLocaleString() ?? '—'}</div>
          <div className="text-xs text-muted-foreground">domains</div>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Blocking</div>
          <div className="flex items-center gap-2 mt-1">
            <Switch
              checked={stats?.enabled ?? false}
              onCheckedChange={handleToggleBlocking}
              disabled={!stats?.success}
            />
            <span className="text-sm font-medium">{stats?.enabled ? 'On' : 'Off'}</span>
          </div>
        </div>
      </div>

      {/* Top domains */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium">Top Queried Domains</h3>
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchTop()}>↻</Button>
          </div>
          {topLoading ? (
            <div className="text-sm text-muted-foreground">Loading...</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">Domain</TableHead>
                  <TableHead className="text-xs text-right">Queries</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(topDomains?.queried?.domains ?? []).slice(0, 10).map((d, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs font-mono truncate max-w-xs">{d.domain}</TableCell>
                    <TableCell className="text-xs text-right">{d.count.toLocaleString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium">Top Blocked Domains</h3>
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchTop()}>↻</Button>
          </div>
          {topLoading ? (
            <div className="text-sm text-muted-foreground">Loading...</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">Domain</TableHead>
                  <TableHead className="text-xs text-right">Blocked</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(topDomains?.blocked?.domains ?? []).slice(0, 10).map((d, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs font-mono text-red-400 truncate max-w-xs">{d.domain}</TableCell>
                    <TableCell className="text-xs text-right">{d.count.toLocaleString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </div>

      {/* Pi-hole system */}
      {system?.success && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="text-sm font-medium mb-3">Pi-hole System ({system.hostname})</h3>
          <div className="flex gap-6 text-sm">
            <div><span className="text-muted-foreground">CPU (1m):</span> {system.cpu_load_1m.toFixed(2)}</div>
            <div><span className="text-muted-foreground">CPU (5m):</span> {system.cpu_load_5m.toFixed(2)}</div>
            <div><span className="text-muted-foreground">RAM:</span> {ramPct}% ({system.ram_used_mb} / {system.ram_total_mb} MB)</div>
            <div><span className="text-muted-foreground">Uptime:</span> {formatUptime(system.uptime_seconds)}</div>
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser** — DNS tab should show Pi-hole stats, top domain tables, system info.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/DnsPage.tsx
git commit -m "feat: implement DnsPage with Pi-hole stats, top domains, system info"
```

---

## Task 10: FirewallPage

**Files:**
- Modify: `dashboard/src/pages/FirewallPage.tsx`

- [ ] **Step 1: Replace `dashboard/src/pages/FirewallPage.tsx`**

```tsx
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'

function AddPortForwardDialog({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({
    name: '', external_port: '', internal_ip: '', internal_port: '', protocol: 'tcp',
  })

  const handleAdd = async () => {
    if (!form.name || !form.external_port || !form.internal_ip || !form.internal_port) {
      toast.error('All fields required')
      return
    }
    try {
      await api.addPortForward({
        name: form.name,
        external_port: parseInt(form.external_port),
        internal_ip: form.internal_ip,
        internal_port: parseInt(form.internal_port),
        protocol: form.protocol,
      })
      toast.success(`Port forward "${form.name}" added`)
      onAdded()
      setOpen(false)
      setForm({ name: '', external_port: '', internal_ip: '', internal_port: '', protocol: 'tcp' })
    } catch {
      toast.error('Failed to add port forward')
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" className="h-7 text-xs">+ Add Rule</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Port Forward</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          {([
            { id: 'name', label: 'Name', placeholder: 'e.g. Minecraft' },
            { id: 'external_port', label: 'External Port', placeholder: '25565' },
            { id: 'internal_ip', label: 'Internal IP', placeholder: '192.168.0.50' },
            { id: 'internal_port', label: 'Internal Port', placeholder: '25565' },
          ] as const).map(({ id, label, placeholder }) => (
            <div key={id} className="space-y-1">
              <Label>{label}</Label>
              <Input
                value={form[id]}
                onChange={e => setForm(f => ({ ...f, [id]: e.target.value }))}
                placeholder={placeholder}
              />
            </div>
          ))}
          <div className="space-y-1">
            <Label>Protocol</Label>
            <select
              className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              value={form.protocol}
              onChange={e => setForm(f => ({ ...f, protocol: e.target.value }))}
            >
              <option value="tcp">TCP</option>
              <option value="udp">UDP</option>
              <option value="both">Both</option>
            </select>
          </div>
          <Button onClick={handleAdd} className="w-full">Add Rule</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default function FirewallPage() {
  const queryClient = useQueryClient()
  const [removing, setRemoving] = useState<string | null>(null)

  const { data: ports, isLoading: portsLoading, refetch: refetchPorts } = useQuery({
    queryKey: ['ports'],
    queryFn: api.getPortForwards,
  })

  const { data: upnp, isLoading: upnpLoading, refetch: refetchUpnp } = useQuery({
    queryKey: ['upnp'],
    queryFn: api.getUpnp,
  })

  const handleRemove = async (ruleId: string, name: string) => {
    if (!confirm(`Remove port forward "${name}"?`)) return
    setRemoving(ruleId)
    try {
      await api.removePortForward(ruleId)
      toast.success(`Removed "${name}"`)
      queryClient.invalidateQueries({ queryKey: ['ports'] })
    } catch {
      toast.error('Failed to remove rule')
    } finally {
      setRemoving(null)
    }
  }

  return (
    <div className="space-y-6">
      {/* Port forwards */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">Port Forwards</h3>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchPorts()}>↻</Button>
            <AddPortForwardDialog onAdded={() => queryClient.invalidateQueries({ queryKey: ['ports'] })} />
          </div>
        </div>
        {portsLoading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : ports?.success ? (
          ports.rules.length === 0 ? (
            <div className="text-sm text-muted-foreground">No port forward rules configured.</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">Name</TableHead>
                  <TableHead className="text-xs">Ext Port</TableHead>
                  <TableHead className="text-xs">Internal</TableHead>
                  <TableHead className="text-xs">Protocol</TableHead>
                  <TableHead className="text-xs"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ports.rules.map((rule) => (
                  <TableRow key={rule.id ?? rule.name}>
                    <TableCell className="text-xs">{rule.name}</TableCell>
                    <TableCell className="text-xs font-mono">{rule.external_port}</TableCell>
                    <TableCell className="text-xs font-mono">{rule.internal_ip}:{rule.internal_port}</TableCell>
                    <TableCell className="text-xs uppercase">{rule.protocol}</TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2 text-xs text-red-500 hover:text-red-600"
                        disabled={removing === rule.id}
                        onClick={() => rule.id && handleRemove(rule.id, rule.name)}
                      >
                        Remove
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )
        ) : (
          <div className="text-sm text-muted-foreground">{ports?.error ?? 'Could not load rules'}</div>
        )}
      </div>

      {/* UPnP port maps */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium">UPnP Port Mappings</h3>
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchUpnp()}>↻</Button>
        </div>
        {upnpLoading ? (
          <div className="text-sm text-muted-foreground">Loading...</div>
        ) : upnp?.portmaps?.mappings?.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Description</TableHead>
                <TableHead className="text-xs">Ext Port</TableHead>
                <TableHead className="text-xs">Internal</TableHead>
                <TableHead className="text-xs">Protocol</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {upnp.portmaps.mappings.map((m, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs">{m.description || '—'}</TableCell>
                  <TableCell className="text-xs font-mono">{m.external_port}</TableCell>
                  <TableCell className="text-xs font-mono">{m.internal_host}:{m.internal_port}</TableCell>
                  <TableCell className="text-xs uppercase">{m.protocol}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="text-sm text-muted-foreground">
            {upnp?.portmaps?.error ?? (upnp?.portmaps?.available === false ? 'No UPnP gateway found' : 'No active UPnP mappings')}
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser** — Firewall tab should show port forwards table with Add/Remove, and UPnP maps table.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/FirewallPage.tsx
git commit -m "feat: implement FirewallPage with port forwards and UPnP maps"
```

---

## Task 11: Production build + smoke verify

**Files:**
- No new files (builds to `dashboard/dist/` which is gitignored)
- Modify: `CLAUDE.md` — update status

- [ ] **Step 1: Build the React app**

```bash
cd dashboard && npm run build
```
Expected: `dist/` directory created with `index.html` and hashed JS/CSS assets. No TypeScript errors.

If there are TypeScript errors, fix them before proceeding.

- [ ] **Step 2: Verify the dashboard is served by the MCP server**

Make sure the MCP server is running:
```bash
# In a separate terminal (if not already running):
.venv/bin/python -m src.server
```

Then open **http://localhost:8000** in a browser. Expected:
- Dashboard loads (not a 404 or JSON error)
- Header shows 🛜 Network Assistant with four tab buttons
- Overview tab loads with real data or error cards (depending on whether devices are reachable)
- Theme toggle works (switches between dark/light)
- Tab navigation works

- [ ] **Step 3: Verify the Vite proxy still works for development**

```bash
cd dashboard && npm run dev
```
Open http://localhost:5173 — should behave identically to the production build with live reload.

- [ ] **Step 4: Update CLAUDE.md status**

In CLAUDE.md, append to the Status section:

```markdown
**Dashboard complete (2026-06-04).** React + Vite dashboard served from the MCP server at `http://localhost:8000`. 4 tabs: Overview (stat cards + 24h trends chart), Network (mesh nodes + device inventory), DNS (Pi-hole stats + top domains), Firewall (port forwards + UPnP maps). Auto-refresh: 30s for stats/mesh, 5min for trends, manual for tables. Dark/light toggle. Backend: `src/api.py` (async handlers) + `@mcp.custom_route` in `server.py`. Frontend: `dashboard/` (React, shadcn/ui, Recharts, TanStack Query). Dev: `cd dashboard && npm run dev` (proxies /api/* to :8000). Build: `cd dashboard && npm run build` → served from :8000.
```

- [ ] **Step 5: Commit**

```bash
cd ..
git add src/server.py src/api.py tests/test_api.py CLAUDE.md
# dashboard/dist is gitignored — only commit source changes
git add dashboard/src/ dashboard/package.json dashboard/vite.config.ts dashboard/tsconfig*.json dashboard/tailwind.config.js dashboard/postcss.config.js dashboard/components.json dashboard/index.html
git commit -m "feat: network assistant dashboard — React UI served from MCP server"
```

- [ ] **Step 6: Push to GitHub**

```bash
git push
```
