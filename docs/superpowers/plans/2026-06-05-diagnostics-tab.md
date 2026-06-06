# Diagnostics Tab + DNS Page Additions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Diagnostics tab to the dashboard with 7 interactive network tools, and 3 new cards to the DNS tab (Top Clients, Domain Manager, Known Clients).

**Architecture:** New backend API routes in `src/api.py` + `src/server.py` expose existing MCP tool functions over HTTP. The React frontend adds a new `DiagnosticsPage.tsx` and extends `DnsPage.tsx`. Each diagnostic tool maintains its own `null | 'running' | result` state; results expand inline below the control that triggered them.

**Tech Stack:** Python/Starlette backend (existing pattern), React + TypeScript + TanStack Query frontend (existing pattern), shadcn/ui components, Tailwind CSS v3.

---

## File Map

**Create:**
- `dashboard/src/pages/DiagnosticsPage.tsx`

**Modify:**
- `src/api.py` — add 11 handler functions
- `src/server.py` — add 10 new routes (before the `/{path:path}` catch-all)
- `tests/test_api.py` — add tests for all new routes
- `dashboard/src/lib/types.ts` — add 9 new interfaces
- `dashboard/src/lib/api.ts` — add 10 new API call functions
- `dashboard/src/pages/DnsPage.tsx` — add 3 new cards
- `dashboard/src/App.tsx` — add Diagnostics tab

---

## Task 1: Backend — Diagnostics routes (ping, traceroute, speedtest, DNS lookup)

**Files:**
- Modify: `src/api.py`
- Modify: `src/server.py` (add 4 routes before the `/{path:path}` catch-all at line 466)
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_api.py`:

```python
from unittest.mock import AsyncMock, patch, MagicMock
import src.server as server_module
from starlette.testclient import TestClient


def test_ping_route_success():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api._ping_host", return_value={
             "success": True, "host": "8.8.8.8",
             "avg_ms": 12.3, "packet_loss_pct": 0.0, "reachable": True,
         }):
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/diagnostics/ping", json={"host": "8.8.8.8"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["host"] == "8.8.8.8"


def test_ping_route_missing_host():
    with patch("src.server._cfg", _mock_cfg()):
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/diagnostics/ping", json={})
        assert resp.status_code == 400


def test_traceroute_route_success():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api._traceroute_host", return_value={
             "success": True, "host": "1.1.1.1",
             "hops": [{"hop": 1, "ip": "192.168.0.1", "ms": 1.2}],
         }):
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/diagnostics/traceroute", json={"host": "1.1.1.1"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True


def test_speedtest_route_success():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api._run_speedtest", return_value={
             "success": True, "download_mbps": 942.1, "upload_mbps": 487.3, "ping_ms": 11.0,
         }):
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/diagnostics/speedtest")
        assert resp.status_code == 200
        assert resp.json()["download_mbps"] == 942.1


def test_dns_lookup_route_success():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api._test_dns_resolution", return_value={
             "success": True, "hostname": "example.com",
             "addresses": ["93.184.216.34"], "elapsed_ms": 8.2,
         }):
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/diagnostics/dns", json={"hostname": "example.com"})
        assert resp.status_code == 200
        assert resp.json()["addresses"] == ["93.184.216.34"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant
.venv/bin/pytest tests/test_api.py::test_ping_route_success tests/test_api.py::test_speedtest_route_success -v
```

Expected: `FAILED` — routes don't exist yet.

- [ ] **Step 3: Add imports and handler functions to `src/api.py`**

Add after the existing imports at the top of `src/api.py`:

```python
from src.tools.diagnostics import (
    ping_host as _ping_host,
    traceroute_host as _traceroute_host,
    run_speedtest as _run_speedtest,
    test_dns_resolution as _test_dns_resolution,
)
```

Add these functions at the bottom of `src/api.py` (before end of file):

```python
async def diag_ping(host: str, count: int = 4) -> dict:
    return await asyncio.to_thread(_ping_host, host, count)


async def diag_traceroute(host: str) -> dict:
    return await asyncio.to_thread(_traceroute_host, host)


async def diag_speedtest() -> dict:
    return await asyncio.to_thread(_run_speedtest)


async def diag_dns(hostname: str) -> dict:
    return await asyncio.to_thread(_test_dns_resolution, hostname)
```

- [ ] **Step 4: Add 4 routes to `src/server.py`**

Add the following before the `# Must be last — catch-all for React SPA` comment (currently at line 465):

```python
@mcp.custom_route("/api/diagnostics/ping", methods=["POST"])
async def _api_ping(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    try:
        body = await request.json()
        host = body.get("host", "").strip()
        if not host:
            return JSONResponse({"success": False, "error": "host is required"}, status_code=400)
        count = int(body.get("count", 4))
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)
    return JSONResponse(await api.diag_ping(host, count))


@mcp.custom_route("/api/diagnostics/traceroute", methods=["POST"])
async def _api_traceroute(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    try:
        body = await request.json()
        host = body.get("host", "").strip()
        if not host:
            return JSONResponse({"success": False, "error": "host is required"}, status_code=400)
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)
    return JSONResponse(await api.diag_traceroute(host))


@mcp.custom_route("/api/diagnostics/speedtest", methods=["POST"])
async def _api_speedtest(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.diag_speedtest())


@mcp.custom_route("/api/diagnostics/dns", methods=["POST"])
async def _api_dns(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    try:
        body = await request.json()
        hostname = body.get("hostname", "").strip()
        if not hostname:
            return JSONResponse({"success": False, "error": "hostname is required"}, status_code=400)
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)
    return JSONResponse(await api.diag_dns(hostname))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_api.py::test_ping_route_success tests/test_api.py::test_ping_route_missing_host tests/test_api.py::test_traceroute_route_success tests/test_api.py::test_speedtest_route_success tests/test_api.py::test_dns_lookup_route_success -v
```

Expected: all 5 `PASSED`.

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
.venv/bin/pytest -v
```

Expected: all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add src/api.py src/server.py tests/test_api.py
git commit -m "feat: add diagnostics API routes (ping, traceroute, speedtest, dns)"
```

---

## Task 2: Backend — WAN speed compare + Pi-hole gravity routes

**Files:**
- Modify: `src/api.py`
- Modify: `src/server.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_api.py`:

```python
def test_wan_speed_compare_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.WANSpeedClient") as mock_speed:
        mock_speed.return_value.compare_wan_speed.return_value = {
            "success": True, "quick": True,
            "wan1": {"latency_ms": 12.0, "packet_loss_pct": 0.0},
            "wan2": {"latency_ms": 28.0, "packet_loss_pct": 0.0},
            "recommendation": "WAN1 recommended — 2.3× lower latency",
            "restored": True,
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/wan/speed/compare", json={"quick": True})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["recommendation"] == "WAN1 recommended — 2.3× lower latency"


def test_pihole_gravity_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.update_gravity.return_value = {
            "success": True, "message": "Gravity update triggered — runs in background on Pi-hole",
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/pihole/gravity")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_api.py::test_wan_speed_compare_route tests/test_api.py::test_pihole_gravity_route -v
```

Expected: `FAILED`.

- [ ] **Step 3: Add imports and handlers to `src/api.py`**

Add after the existing imports:

```python
from src.tools.wan_speed import WANSpeedClient
```

Add handler functions at the bottom of `src/api.py`:

```python
async def wan_speed_compare(cfg: Config, quick: bool = True) -> dict:
    return await asyncio.to_thread(WANSpeedClient(**vars(cfg.er605)).compare_wan_speed, quick)


async def pihole_gravity(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).update_gravity)
```

- [ ] **Step 4: Add routes to `src/server.py`** (before the catch-all)

```python
@mcp.custom_route("/api/wan/speed/compare", methods=["POST"])
async def _api_wan_speed_compare(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    try:
        body = await request.json()
        quick = bool(body.get("quick", True))
    except Exception:
        quick = True
    return JSONResponse(await api.wan_speed_compare(_cfg, quick))


@mcp.custom_route("/api/pihole/gravity", methods=["POST"])
async def _api_pihole_gravity(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.pihole_gravity(_cfg))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_api.py::test_wan_speed_compare_route tests/test_api.py::test_pihole_gravity_route -v
```

Expected: both `PASSED`.

- [ ] **Step 6: Run full suite**

```bash
.venv/bin/pytest -v
```

- [ ] **Step 7: Commit**

```bash
git add src/api.py src/server.py tests/test_api.py
git commit -m "feat: add WAN speed compare and Pi-hole gravity API routes"
```

---

## Task 3: Backend — Pi-hole top-clients, clients, and domains routes

**Files:**
- Modify: `src/api.py`
- Modify: `src/server.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_api.py`:

```python
def test_pihole_top_clients_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.get_top_clients.return_value = {
            "success": True,
            "clients": [{"ip": "192.168.0.50", "name": "laptop", "count": 1234}],
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.get("/api/pihole/top-clients")
        assert resp.status_code == 200
        assert resp.json()["clients"][0]["ip"] == "192.168.0.50"


def test_pihole_clients_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.get_clients.return_value = {
            "success": True,
            "clients": [{"ip": "192.168.0.50", "hostname": "laptop", "query_count": 5000, "last_query": 1700000000}],
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.get("/api/pihole/clients")
        assert resp.status_code == 200
        assert len(resp.json()["clients"]) == 1


def test_pihole_domains_get_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.get_domain_lists.return_value = {
            "success": True,
            "allow": [{"domain": "t.co", "kind": "exact", "enabled": True, "comment": ""}],
            "block": [],
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.get("/api/pihole/domains")
        assert resp.status_code == 200
        assert resp.json()["allow"][0]["domain"] == "t.co"


def test_pihole_domains_post_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.add_domain.return_value = {
            "success": True, "domain": "ads.example.com", "list_type": "block", "kind": "exact",
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.post("/api/pihole/domains", json={
            "domain": "ads.example.com", "list_type": "block", "kind": "exact",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True


def test_pihole_domains_delete_route():
    with patch("src.server._cfg", _mock_cfg()), \
         patch("src.api.PiholeClient") as mock_pihole:
        mock_pihole.return_value.remove_domain.return_value = {
            "success": True, "domain": "ads.example.com", "list_type": "block", "kind": "exact",
        }
        client = TestClient(server_module.mcp.sse_app())
        resp = client.delete("/api/pihole/domains/block/exact/ads.example.com")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_api.py::test_pihole_top_clients_route tests/test_api.py::test_pihole_domains_get_route -v
```

Expected: `FAILED`.

- [ ] **Step 3: Add handlers to `src/api.py`**

```python
async def pihole_top_clients(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_top_clients)


async def pihole_clients(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_clients)


async def pihole_domains(cfg: Config) -> dict:
    return await asyncio.to_thread(PiholeClient(**vars(cfg.pihole)).get_domain_lists)


async def pihole_add_domain(cfg: Config, domain: str, list_type: str, kind: str) -> dict:
    return await asyncio.to_thread(
        PiholeClient(**vars(cfg.pihole)).add_domain, domain, list_type=list_type, kind=kind
    )


async def pihole_remove_domain(cfg: Config, domain: str, list_type: str, kind: str) -> dict:
    return await asyncio.to_thread(
        PiholeClient(**vars(cfg.pihole)).remove_domain, domain, list_type=list_type, kind=kind
    )
```

- [ ] **Step 4: Add routes to `src/server.py`** (before the catch-all)

```python
@mcp.custom_route("/api/pihole/top-clients", methods=["GET"])
async def _api_pihole_top_clients(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.pihole_top_clients(_cfg))


@mcp.custom_route("/api/pihole/clients", methods=["GET"])
async def _api_pihole_clients(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    return JSONResponse(await api.pihole_clients(_cfg))


@mcp.custom_route("/api/pihole/domains", methods=["GET", "POST"])
async def _api_pihole_domains(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    if request.method == "POST":
        try:
            body = await request.json()
            domain = body.get("domain", "").strip()
            if not domain:
                return JSONResponse({"success": False, "error": "domain is required"}, status_code=400)
            list_type = body.get("list_type", "block")
            kind = body.get("kind", "exact")
        except Exception:
            return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)
        return JSONResponse(await api.pihole_add_domain(_cfg, domain, list_type, kind))
    return JSONResponse(await api.pihole_domains(_cfg))


@mcp.custom_route("/api/pihole/domains/{list_type}/{kind}/{domain:path}", methods=["DELETE"])
async def _api_pihole_domain_delete(request: Request) -> JSONResponse:
    if not _cfg:
        return JSONResponse(_NO_CONFIG, status_code=503)
    list_type = request.path_params["list_type"]
    kind = request.path_params["kind"]
    domain = request.path_params["domain"]
    return JSONResponse(await api.pihole_remove_domain(_cfg, domain, list_type, kind))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_api.py::test_pihole_top_clients_route tests/test_api.py::test_pihole_clients_route tests/test_api.py::test_pihole_domains_get_route tests/test_api.py::test_pihole_domains_post_route tests/test_api.py::test_pihole_domains_delete_route -v
```

Expected: all 5 `PASSED`.

- [ ] **Step 6: Run full suite**

```bash
.venv/bin/pytest -v
```

- [ ] **Step 7: Commit**

```bash
git add src/api.py src/server.py tests/test_api.py
git commit -m "feat: add Pi-hole clients and domain management API routes"
```

---

## Task 4: Frontend — TypeScript types and api.ts functions

**Files:**
- Modify: `dashboard/src/lib/types.ts`
- Modify: `dashboard/src/lib/api.ts`

- [ ] **Step 1: Add new interfaces to `dashboard/src/lib/types.ts`**

Append to the end of `types.ts`:

```typescript
export interface PingResult {
  success: boolean
  host: string
  packets_sent?: number
  packet_loss_pct?: number
  avg_ms?: number | null
  reachable?: boolean
  error?: string
  suggestion?: string
}

export interface TracerouteHop {
  hop: number
  ip: string | null
  ms: number | null
  timeout?: boolean
}

export interface TracerouteResult {
  success: boolean
  host: string
  hops: TracerouteHop[]
  raw?: string
  error?: string
  suggestion?: string
}

export interface SpeedtestResult {
  success: boolean
  download_mbps?: number
  upload_mbps?: number
  ping_ms?: number
  server?: string
  server_location?: string
  error?: string
  suggestion?: string
}

export interface DnsLookupResult {
  success: boolean
  hostname: string
  dns_server?: string
  addresses?: string[]
  elapsed_ms?: number
  error?: string
  suggestion?: string
}

export interface WANProbeResult {
  avg_latency_ms: number | null
  packet_loss_pct: number
  degraded: boolean
}

export interface WANHealthCompare {
  success: boolean
  wan1_probe?: WANProbeResult | null
  wan2_probe?: WANProbeResult | null
  recommendation?: string
  restored?: boolean
  error?: string
}

export interface WANSpeedMeasure {
  latency_ms?: number | null
  packet_loss_pct?: number
  download_mbps?: number
  upload_mbps?: number
  server?: string
}

export interface WANSpeedCompare {
  success: boolean
  quick: boolean
  wan1?: WANSpeedMeasure | null
  wan2?: WANSpeedMeasure | null
  recommendation?: string
  restored?: boolean
  error?: string
}

export interface GravityResult {
  success: boolean
  message?: string
  error?: string
}

export interface TopClient {
  ip: string
  name: string
  count: number
}

export interface TopClientsResult {
  success: boolean
  clients: TopClient[]
  error?: string
}

export interface PiholeClientEntry {
  ip: string
  hostname: string
  query_count: number
  last_query: number
}

export interface PiholeClientsResult {
  success: boolean
  clients: PiholeClientEntry[]
  error?: string
}

export interface PiholeDomainListEntry {
  domain: string
  kind: 'exact' | 'regex'
  enabled: boolean
  comment: string
}

export interface DomainLists {
  success: boolean
  allow: PiholeDomainListEntry[]
  block: PiholeDomainListEntry[]
  error?: string
}
```

- [ ] **Step 2: Add 10 new functions to `dashboard/src/lib/api.ts`**

Add to the `api` export object:

```typescript
  // Diagnostics
  ping: (host: string, count?: number) =>
    post<PingResult>('/diagnostics/ping', { host, count: count ?? 4 }),
  traceroute: (host: string) =>
    post<TracerouteResult>('/diagnostics/traceroute', { host }),
  speedtest: () =>
    post<SpeedtestResult>('/diagnostics/speedtest'),
  dnsLookup: (hostname: string) =>
    post<DnsLookupResult>('/diagnostics/dns', { hostname }),
  compareWanSpeed: (quick: boolean) =>
    post<WANSpeedCompare>('/wan/speed/compare', { quick }),
  updateGravity: () =>
    post<GravityResult>('/pihole/gravity'),

  // DNS page extras
  getPiholeTopClients: () =>
    get<TopClientsResult>('/pihole/top-clients'),
  getPiholeClients: () =>
    get<PiholeClientsResult>('/pihole/clients'),
  getDomainLists: () =>
    get<DomainLists>('/pihole/domains'),
  addDomain: (domain: string, list_type: string, kind: string) =>
    post<{ success: boolean; error?: string }>('/pihole/domains', { domain, list_type, kind }),
  removeDomain: (list_type: string, kind: string, domain: string) =>
    del<{ success: boolean; error?: string }>(`/pihole/domains/${encodeURIComponent(list_type)}/${encodeURIComponent(kind)}/${encodeURIComponent(domain)}`),
```

Also add these imports at the top of `api.ts`:

```typescript
import type {
  Snapshot, WANHealth, QueryTrends, TopDomainsResult, PiholeStats,
  PiholeSystem, MeshHealth, DeviceList, UPnPResult, PortForwards,
  PingResult, TracerouteResult, SpeedtestResult, DnsLookupResult,
  WANHealthCompare, WANSpeedCompare, GravityResult,
  TopClientsResult, PiholeClientsResult, DomainLists,
} from './types'
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant/dashboard
npm run build 2>&1 | grep -E "error|Error" | head -20
```

Expected: no TypeScript errors (chunk size warnings are fine).

- [ ] **Step 4: Commit**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant
git add dashboard/src/lib/types.ts dashboard/src/lib/api.ts
git commit -m "feat: add TypeScript types and api.ts functions for diagnostics and DNS extras"
```

---

## Task 5: Frontend — DiagnosticsPage Quick Actions section

**Files:**
- Create: `dashboard/src/pages/DiagnosticsPage.tsx`

- [ ] **Step 1: Create `DiagnosticsPage.tsx` with Quick Actions**

```tsx
import { useState } from 'react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import type {
  SpeedtestResult, WANHealthCompare, WANSpeedCompare, GravityResult,
  PingResult, TracerouteResult, DnsLookupResult,
} from '@/lib/types'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'

type ToolState<T> = null | 'running' | T

async function runTool<T>(
  setter: (s: ToolState<T>) => void,
  fn: () => Promise<T>,
) {
  setter('running')
  try {
    setter(await fn())
  } catch {
    setter({ success: false, error: 'Request failed' } as T)
  }
}

function ResultBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-2 rounded-md border border-border bg-muted/40 p-3 text-xs font-mono space-y-1">
      {children}
    </div>
  )
}

function ErrorLine({ error, suggestion }: { error?: string; suggestion?: string }) {
  return (
    <>
      <div className="text-red-400">{error ?? 'Unknown error'}</div>
      {suggestion && <div className="text-muted-foreground">{suggestion}</div>}
    </>
  )
}

function SpeedtestCard() {
  const [result, setResult] = useState<ToolState<SpeedtestResult>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Speed Test</span>
        <Button
          size="sm"
          className="h-7 text-xs"
          disabled={result === 'running'}
          onClick={() => runTool(setResult, api.speedtest)}
        >
          {result === 'running' ? 'Running…' : 'Run'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success ? (
            <>
              <div className="text-green-400">↓ {result.download_mbps} Mbps &nbsp; ↑ {result.upload_mbps} Mbps &nbsp; ping {result.ping_ms} ms</div>
              {result.server && <div className="text-muted-foreground">{result.server} — {result.server_location}</div>}
            </>
          ) : <ErrorLine error={result.error} suggestion={result.suggestion} />}
        </ResultBox>
      )}
    </div>
  )
}

function WANHealthCompareCard() {
  const [result, setResult] = useState<ToolState<WANHealthCompare>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Compare WAN Health</span>
        <Button
          size="sm"
          className="h-7 text-xs"
          disabled={result === 'running'}
          onClick={() => runTool(setResult, api.compareWan)}
        >
          {result === 'running' ? 'Running…' : 'Run'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success ? (
            <>
              {result.wan1_probe && <div>WAN1: {result.wan1_probe.avg_latency_ms}ms · {result.wan1_probe.packet_loss_pct}% loss{result.wan1_probe.degraded ? ' ⚠ degraded' : ''}</div>}
              {result.wan2_probe && <div>WAN2: {result.wan2_probe.avg_latency_ms}ms · {result.wan2_probe.packet_loss_pct}% loss{result.wan2_probe.degraded ? ' ⚠ degraded' : ''}</div>}
              {result.recommendation && <div className="text-green-400 mt-1">{result.recommendation}</div>}
            </>
          ) : <ErrorLine error={result.error} />}
        </ResultBox>
      )}
    </div>
  )
}

function WANSpeedCompareCard() {
  const [quick, setQuick] = useState(true)
  const [result, setResult] = useState<ToolState<WANSpeedCompare>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium">Compare WAN Speed</span>
          <div className="flex items-center gap-1.5">
            <Switch
              checked={!quick}
              onCheckedChange={v => setQuick(!v)}
              disabled={result === 'running'}
            />
            <Label className="text-xs text-muted-foreground">{quick ? 'Quick' : 'Full'}</Label>
          </div>
        </div>
        <Button
          size="sm"
          className="h-7 text-xs"
          disabled={result === 'running'}
          onClick={() => runTool(setResult, () => api.compareWanSpeed(quick))}
        >
          {result === 'running' ? 'Running…' : 'Run'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success ? (
            <>
              {result.wan1 && <div>WAN1: {result.quick ? `${result.wan1.latency_ms}ms latency` : `↓${result.wan1.download_mbps} ↑${result.wan1.upload_mbps} Mbps · ${result.wan1.latency_ms}ms`}</div>}
              {result.wan2 && <div>WAN2: {result.quick ? `${result.wan2.latency_ms}ms latency` : `↓${result.wan2.download_mbps} ↑${result.wan2.upload_mbps} Mbps · ${result.wan2.latency_ms}ms`}</div>}
              {result.recommendation && <div className="text-green-400 mt-1">{result.recommendation}</div>}
            </>
          ) : <ErrorLine error={result.error} />}
        </ResultBox>
      )}
    </div>
  )
}

function GravityCard() {
  const [result, setResult] = useState<ToolState<GravityResult>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Update Pi-hole Gravity</span>
        <Button
          size="sm"
          className="h-7 text-xs"
          disabled={result === 'running'}
          onClick={() => runTool(setResult, api.updateGravity)}
        >
          {result === 'running' ? 'Running…' : 'Run'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success
            ? <div className="text-green-400">{result.message}</div>
            : <ErrorLine error={result.error} />}
        </ResultBox>
      )}
    </div>
  )
}

function PingCard() {
  const [host, setHost] = useState('8.8.8.8')
  const [result, setResult] = useState<ToolState<PingResult>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium w-24 shrink-0">Ping</span>
        <Input
          className="h-7 text-xs font-mono"
          value={host}
          onChange={e => setHost(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && host.trim() && runTool(setResult, () => api.ping(host.trim()))}
          placeholder="host or IP"
        />
        <Button
          size="sm"
          className="h-7 text-xs shrink-0"
          disabled={result === 'running' || !host.trim()}
          onClick={() => runTool(setResult, () => api.ping(host.trim()))}
        >
          {result === 'running' ? '…' : 'Go'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success
            ? <div className={result.reachable ? 'text-green-400' : 'text-red-400'}>
                {result.reachable ? `${result.avg_ms}ms avg · ${result.packet_loss_pct}% loss` : `Unreachable — ${result.packet_loss_pct}% loss`}
              </div>
            : <ErrorLine error={result.error} suggestion={result.suggestion} />}
        </ResultBox>
      )}
    </div>
  )
}

function TracerouteCard() {
  const [host, setHost] = useState('1.1.1.1')
  const [result, setResult] = useState<ToolState<TracerouteResult>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium w-24 shrink-0">Traceroute</span>
        <Input
          className="h-7 text-xs font-mono"
          value={host}
          onChange={e => setHost(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && host.trim() && runTool(setResult, () => api.traceroute(host.trim()))}
          placeholder="host or IP"
        />
        <Button
          size="sm"
          className="h-7 text-xs shrink-0"
          disabled={result === 'running' || !host.trim()}
          onClick={() => runTool(setResult, () => api.traceroute(host.trim()))}
        >
          {result === 'running' ? '…' : 'Go'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success ? (
            result.hops.length === 0
              ? <div className="text-muted-foreground">No hops recorded</div>
              : result.hops.map(h => (
                  <div key={h.hop}>
                    <span className="text-muted-foreground w-5 inline-block">{h.hop}</span>
                    {h.timeout ? <span className="text-muted-foreground">* * *</span> : (
                      <><span className="text-foreground">{h.ip}</span><span className="text-muted-foreground ml-2">{h.ms}ms</span></>
                    )}
                  </div>
                ))
          ) : <ErrorLine error={result.error} suggestion={result.suggestion} />}
        </ResultBox>
      )}
    </div>
  )
}

function DnsLookupCard() {
  const [hostname, setHostname] = useState('')
  const [result, setResult] = useState<ToolState<DnsLookupResult>>(null)
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium w-24 shrink-0">DNS Lookup</span>
        <Input
          className="h-7 text-xs font-mono"
          value={hostname}
          onChange={e => setHostname(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && hostname.trim() && runTool(setResult, () => api.dnsLookup(hostname.trim()))}
          placeholder="hostname"
        />
        <Button
          size="sm"
          className="h-7 text-xs shrink-0"
          disabled={result === 'running' || !hostname.trim()}
          onClick={() => runTool(setResult, () => api.dnsLookup(hostname.trim()))}
        >
          {result === 'running' ? '…' : 'Go'}
        </Button>
      </div>
      {result && result !== 'running' && (
        <ResultBox>
          {result.success ? (
            <>
              {result.addresses?.map((a, i) => <div key={i} className="text-green-400">{a}</div>)}
              <div className="text-muted-foreground">via {result.dns_server} · {result.elapsed_ms}ms</div>
            </>
          ) : <ErrorLine error={result.error} suggestion={result.suggestion} />}
        </ResultBox>
      )}
    </div>
  )
}

export default function DiagnosticsPage() {
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium mb-3">Quick Actions</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <SpeedtestCard />
          <WANHealthCompareCard />
          <WANSpeedCompareCard />
          <GravityCard />
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium mb-3">Lookups</h3>
        <div className="space-y-3">
          <PingCard />
          <TracerouteCard />
          <DnsLookupCard />
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Check TypeScript compiles**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant/dashboard
npm run build 2>&1 | grep -E "^.*error TS" | head -20
```

Expected: no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant
git add dashboard/src/pages/DiagnosticsPage.tsx
git commit -m "feat: add DiagnosticsPage with quick actions and lookup tools"
```

---

## Task 6: Frontend — Wire DiagnosticsPage into App.tsx

**Files:**
- Modify: `dashboard/src/App.tsx`

- [ ] **Step 1: Update `App.tsx`**

Replace the `Tab` type and `TABS` array, add the import, and add the new tab to the render:

```tsx
// Add import at top with other page imports:
import DiagnosticsPage from '@/pages/DiagnosticsPage'

// Replace:
type Tab = 'overview' | 'network' | 'dns' | 'firewall'

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'network', label: 'Network' },
  { id: 'dns', label: 'DNS' },
  { id: 'firewall', label: 'Firewall' },
]

// With:
type Tab = 'overview' | 'network' | 'dns' | 'firewall' | 'diagnostics'

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'network', label: 'Network' },
  { id: 'dns', label: 'DNS' },
  { id: 'firewall', label: 'Firewall' },
  { id: 'diagnostics', label: 'Diagnostics' },
]
```

Also add to the `<main>` section after the `firewall` conditional:

```tsx
{activeTab === 'diagnostics' && <DiagnosticsPage />}
```

- [ ] **Step 2: Build and verify no TypeScript errors**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant/dashboard
npm run build 2>&1 | grep -E "^.*error TS" | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant
git add dashboard/src/App.tsx
git commit -m "feat: add Diagnostics tab to dashboard navigation"
```

---

## Task 7: Frontend — DNS page: Top Clients + Known Clients cards

**Files:**
- Modify: `dashboard/src/pages/DnsPage.tsx`

- [ ] **Step 1: Add imports to `DnsPage.tsx`**

`useQuery`, `useQueryClient`, `Button`, and `Table`/`TableBody`/etc. are already imported. Only add the new imports:

```tsx
// Add to existing type imports in api.ts (merge with existing import):
import type { TopClientsResult, PiholeClientsResult } from '@/lib/types'

// Add as a new import line:
import { formatDistanceToNow } from 'date-fns'
```

Note: `date-fns` may need to be installed. Verify it's available:

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant/dashboard
grep "date-fns" package.json
```

If not present, install it:

```bash
npm install date-fns
```

- [ ] **Step 2: Add two new queries and cards to `DnsPage.tsx`**

Add these queries after the existing `topDomains` query inside the component:

```tsx
const { data: topClients, isLoading: topClientsLoading, refetch: refetchTopClients } = useQuery({
  queryKey: ['pihole-top-clients'],
  queryFn: api.getPiholeTopClients,
})

const { data: allClients, isLoading: allClientsLoading, refetch: refetchAllClients } = useQuery({
  queryKey: ['pihole-clients'],
  queryFn: api.getPiholeClients,
})
```

Add these two cards inside the return JSX, after the `{/* Top domains */}` section and before the closing `</div>`:

```tsx
{/* Top Pi-hole clients */}
<div className="rounded-lg border border-border bg-card p-4">
  <div className="flex items-center justify-between mb-3">
    <h3 className="text-sm font-medium">Top Clients Today</h3>
    <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchTopClients()}>↻</Button>
  </div>
  {topClientsLoading ? (
    <div className="text-sm text-muted-foreground">Loading...</div>
  ) : topClients?.success ? (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="text-xs">IP</TableHead>
          <TableHead className="text-xs">Hostname</TableHead>
          <TableHead className="text-xs text-right">Queries</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {(topClients.clients ?? []).map((c, i) => (
          <TableRow key={i}>
            <TableCell className="text-xs font-mono">{c.ip}</TableCell>
            <TableCell className="text-xs text-muted-foreground">{c.name || '—'}</TableCell>
            <TableCell className="text-xs text-right">{c.count.toLocaleString()}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  ) : (
    <div className="text-sm text-muted-foreground">{topClients?.error ?? 'Could not load clients'}</div>
  )}
</div>

{/* Pi-hole known clients (all-time) */}
<div className="rounded-lg border border-border bg-card p-4">
  <div className="flex items-center justify-between mb-3">
    <h3 className="text-sm font-medium">Known Clients</h3>
    <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchAllClients()}>↻</Button>
  </div>
  {allClientsLoading ? (
    <div className="text-sm text-muted-foreground">Loading...</div>
  ) : allClients?.success ? (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="text-xs">IP</TableHead>
          <TableHead className="text-xs">Hostname</TableHead>
          <TableHead className="text-xs text-right">Total Queries</TableHead>
          <TableHead className="text-xs text-right">Last Seen</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {(allClients.clients ?? [])
          .sort((a, b) => b.query_count - a.query_count)
          .map((c, i) => (
            <TableRow key={i}>
              <TableCell className="text-xs font-mono">{c.ip}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{c.hostname || '—'}</TableCell>
              <TableCell className="text-xs text-right">{c.query_count.toLocaleString()}</TableCell>
              <TableCell className="text-xs text-right text-muted-foreground">
                {c.last_query ? formatDistanceToNow(new Date(c.last_query * 1000), { addSuffix: true }) : '—'}
              </TableCell>
            </TableRow>
          ))}
      </TableBody>
    </Table>
  ) : (
    <div className="text-sm text-muted-foreground">{allClients?.error ?? 'Could not load clients'}</div>
  )}
</div>
```

- [ ] **Step 3: Build and verify**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant/dashboard
npm run build 2>&1 | grep -E "^.*error TS" | head -20
```

- [ ] **Step 4: Commit**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant
git add dashboard/src/pages/DnsPage.tsx
git commit -m "feat: add Top Clients and Known Clients cards to DNS page"
```

---

## Task 8: Frontend — DNS page: Domain Allow/Block Manager

**Files:**
- Modify: `dashboard/src/pages/DnsPage.tsx`

- [ ] **Step 1: Add domain manager state and imports to `DnsPage.tsx`**

Add to the import block:

```tsx
import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'
import type { DomainLists } from '@/lib/types'
```

- [ ] **Step 2: Add domain lists query inside the component**

Add after the existing queries:

```tsx
const { data: domainLists, isLoading: domainListsLoading, refetch: refetchDomains } = useQuery({
  queryKey: ['pihole-domains'],
  queryFn: api.getDomainLists,
})
```

- [ ] **Step 3: Add `AddDomainDialog` component above `DnsPage`**

Add before the `export default function DnsPage()` line:

```tsx
function AddDomainDialog({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [domain, setDomain] = useState('')
  const [listType, setListType] = useState('block')
  const [kind, setKind] = useState('exact')

  const handleAdd = async () => {
    if (!domain.trim()) return
    try {
      await api.addDomain(domain.trim(), listType, kind)
      toast.success(`Added ${domain.trim()} to ${listType}list`)
      onAdded()
      setOpen(false)
      setDomain('')
    } catch {
      toast.error('Failed to add domain')
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" className="h-7 text-xs">+ Add Domain</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Domain to Pi-hole List</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div className="space-y-1">
            <Label>Domain</Label>
            <Input
              value={domain}
              onChange={e => setDomain(e.target.value)}
              placeholder="ads.example.com"
              onKeyDown={e => e.key === 'Enter' && handleAdd()}
            />
          </div>
          <div className="space-y-1">
            <Label>List</Label>
            <select
              className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              value={listType}
              onChange={e => setListType(e.target.value)}
            >
              <option value="block">Blocklist</option>
              <option value="allow">Allowlist</option>
            </select>
          </div>
          <div className="space-y-1">
            <Label>Type</Label>
            <select
              className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
              value={kind}
              onChange={e => setKind(e.target.value)}
            >
              <option value="exact">Exact</option>
              <option value="regex">Regex</option>
            </select>
          </div>
          <Button onClick={handleAdd} className="w-full">Add</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 4: Add Domain Manager card to JSX in `DnsPage`**

Add after the Known Clients card (before the closing `</div>` of the outer `space-y-6` div):

```tsx
{/* Domain Allow/Block Manager */}
<div className="rounded-lg border border-border bg-card p-4">
  <div className="flex items-center justify-between mb-3">
    <h3 className="text-sm font-medium">Domain Lists</h3>
    <div className="flex items-center gap-2">
      <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => refetchDomains()}>↻</Button>
      <AddDomainDialog onAdded={() => refetchDomains()} />
    </div>
  </div>
  {domainListsLoading ? (
    <div className="text-sm text-muted-foreground">Loading...</div>
  ) : domainLists?.success ? (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {(['allow', 'block'] as const).map(listType => (
        <div key={listType}>
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
            {listType === 'allow' ? 'Allowlist' : 'Blocklist'} ({(domainLists[listType] ?? []).length})
          </div>
          {(domainLists[listType] ?? []).length === 0 ? (
            <div className="text-xs text-muted-foreground">Empty</div>
          ) : (
            <div className="space-y-1">
              {(domainLists[listType] ?? []).map((entry, i) => (
                <div key={i} className="flex items-center justify-between gap-2 rounded-md border border-border px-2 py-1">
                  <div className="min-w-0">
                    <span className="text-xs font-mono truncate block">{entry.domain}</span>
                    {entry.kind === 'regex' && <span className="text-xs text-muted-foreground">regex</span>}
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-xs text-red-500 hover:text-red-600 shrink-0"
                    onClick={async () => {
                      try {
                        await api.removeDomain(listType, entry.kind, entry.domain)
                        toast.success(`Removed ${entry.domain}`)
                        refetchDomains()
                      } catch {
                        toast.error('Failed to remove domain')
                      }
                    }}
                  >
                    ✕
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  ) : (
    <div className="text-sm text-muted-foreground">{domainLists?.error ?? 'Could not load domain lists'}</div>
  )}
</div>
```

- [ ] **Step 5: Build and verify**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant/dashboard
npm run build 2>&1 | grep -E "^.*error TS" | head -20
```

Expected: no TypeScript errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant
git add dashboard/src/pages/DnsPage.tsx
git commit -m "feat: add Domain Allow/Block Manager card to DNS page"
```

---

## Task 9: Build dashboard and smoke-test

**Files:** None new — verify build + live test

- [ ] **Step 1: Final build**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant/dashboard
npm run build 2>&1 | tail -5
```

Expected: build completes with no errors (chunk size warnings are fine).

- [ ] **Step 2: Restart server**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant
pkill -f "src.server"; sleep 1
.venv/bin/python -m src.server &
sleep 2
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/
```

Expected: `200`.

- [ ] **Step 3: Verify new API endpoints respond**

```bash
curl -s -X POST http://localhost:8000/api/diagnostics/ping \
  -H "Content-Type: application/json" \
  -d '{"host":"8.8.8.8"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print('success:', d['success'], 'avg_ms:', d.get('avg_ms'))"

curl -s http://localhost:8000/api/pihole/top-clients | python3 -c "import sys,json; d=json.load(sys.stdin); print('clients:', len(d.get('clients',[])))"

curl -s http://localhost:8000/api/pihole/domains | python3 -c "import sys,json; d=json.load(sys.stdin); print('allow:', len(d.get('allow',[])), 'block:', len(d.get('block',[])))"
```

Expected: all return `success: True` with real data.

- [ ] **Step 4: Smoke-test in browser**

Open `http://localhost:8000`. Verify:
- "Diagnostics" tab appears in nav
- Quick Actions: click "Run" on Gravity Update — should show success message
- Lookups: ping `8.8.8.8` — should show latency
- DNS tab: Top Clients Today card shows IP/hostname/count rows
- DNS tab: Known Clients card shows all-time clients with "X ago" last-seen
- DNS tab: Domain Lists card shows Allowlist / Blocklist columns

- [ ] **Step 5: Final commit**

```bash
cd /Users/taylorgay/Documents/Claude/Projects/NetworkAssistant
.venv/bin/pytest -v 2>&1 | tail -5
git add -A
git commit -m "feat: diagnostics tab and DNS page additions complete"
```

Expected pytest output: all tests pass (count should increase from 157 to ~172).
