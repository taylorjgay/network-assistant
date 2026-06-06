# Diagnostics Tab + DNS Page Additions — Design Spec

**Date:** 2026-06-05
**Status:** Approved

---

## Overview

Two deliverables:

1. **New Diagnostics tab** — fifth tab in the dashboard, exposing 7 MCP tools as interactive UI (4 quick-action buttons, 3 input lookups).
2. **DNS page additions** — 3 new cards on the existing DNS tab (Top Clients, Domain Manager, Known Clients).

---

## 1. Diagnostics Tab

### Layout

Two sections within a single page — Quick Actions on top, Lookups below.

#### Quick Actions

Four tools that require no input, rendered as horizontal pills. Each pill has a label, a Run button, and an inline result area that expands below it after execution.

| Tool | Backend call | Notes |
|---|---|---|
| Speed Test | `run_speedtest()` | ~30s; shows download, upload, ping |
| Compare WAN Health | `compare_wan_health()` | ~4s; shows per-WAN latency/loss + recommendation |
| Compare WAN Speed | `compare_wan_speed(quick)` | Quick toggle: latency-only ~15s; Full: Ookla on both WANs ~2min. Requires both WANs powered. |
| Update Pi-hole Gravity | `update_gravity()` | Fires and returns immediately; runs async on Pi |

Compare WAN Speed has a Quick/Full toggle (default: Quick) visible before running.

#### Lookups

Three tools that require a host or domain input, rendered as compact rows (label + text input + Go button + inline result area).

| Tool | Input | Backend call |
|---|---|---|
| Ping | Host or IP | `ping_host(host, count=4)` |
| Traceroute | Host or IP | `traceroute_host(host)` |
| DNS Lookup | Hostname | `test_dns_resolution(hostname)` |

### Result Display

Each tool owns its own result area. Clicking Run/Go:
1. Shows a spinner in place of the button ("Running…")
2. On completion, expands an inline result block directly below that tool
3. Error responses show in the same area with red text

Results persist until the next run of that same tool. Multiple tools can show results simultaneously.

### Loading States

- Button text changes to "Running…" and is disabled during execution
- Long-running tools (Speed Test, Traceroute, full WAN Speed Compare) show elapsed time as a secondary label

---

## 2. DNS Page Additions

Three new cards added below the existing 24h trends chart, in this order:

### 2a. Top Pi-hole Clients

Table showing top 10 DNS clients by query count today.

Columns: IP · Hostname · Queries today

Refresh button (↻). Data fetched on mount, no auto-refresh.

Backend: `GET /api/pihole/top-clients` → `PiholeClient.get_top_clients(count=10)`

### 2b. Domain Allow/Block Manager

Two-column card: Allowlist (left) / Blocklist (right).

Each column lists entries with domain, kind (exact/regex), and a Remove button per entry.

"+ Add Domain" button opens a small dialog:
- Domain field (text input)
- List type: Allow / Block (radio or select)
- Kind: Exact / Regex (radio or select, default: Exact)
- Submit button

On add or remove, re-fetches the domain list to reflect changes.

Backend:
- `GET /api/pihole/domains` → `get_domain_lists()`
- `POST /api/pihole/domains` body `{domain, list_type, kind}` → `add_domain()`
- `DELETE /api/pihole/domains/{list_type}/{kind}/{domain}` → `remove_domain()`

### 2c. Pi-hole Known Clients

Table of all clients Pi-hole has ever seen (all-time, unlike Top Clients which is today only).

Columns: IP · Hostname · Total Queries · Last Seen (relative time, e.g. "2h ago")

Refresh button (↻). Data fetched on mount, no auto-refresh.

Backend: `GET /api/pihole/clients` → `PiholeClient.get_clients()`

---

## New Backend Endpoints

All added to `src/api.py` (handler functions) and `src/server.py` (route registrations).

| Method | Route | Handler | Notes |
|---|---|---|---|
| POST | `/api/diagnostics/ping` | `ping_host(host, count=4)` | Body: `{host, count?}` |
| POST | `/api/diagnostics/traceroute` | `traceroute_host(host)` | Body: `{host}` |
| POST | `/api/diagnostics/speedtest` | `run_speedtest()` | No body |
| POST | `/api/wan/speed/compare` | `compare_wan_speed(quick)` | Body: `{quick: bool}`, default `true` |
| POST | `/api/pihole/gravity` | `update_gravity()` | No body |
| GET | `/api/pihole/top-clients` | `get_top_clients(count=10)` | |
| GET | `/api/pihole/clients` | `get_clients()` | |
| GET | `/api/pihole/domains` | `get_domain_lists()` | |
| POST | `/api/pihole/domains` | `add_domain(domain, list_type, kind)` | Body: `{domain, list_type, kind}` |
| DELETE | `/api/pihole/domains/{list_type}/{kind}/{domain}` | `remove_domain(domain, list_type, kind)` | Path params |

`/api/wan/compare` (Compare WAN Health) already exists — no change needed.

---

## Frontend Files

- **New:** `dashboard/src/pages/DiagnosticsPage.tsx`
- **Modified:** `dashboard/src/pages/DnsPage.tsx` — add 3 new cards
- **Modified:** `dashboard/src/App.tsx` — add Diagnostics tab button + route
- **Modified:** `dashboard/src/lib/api.ts` — add 10 new API call functions
- **Modified:** `dashboard/src/lib/types.ts` — add response types for new endpoints

---

## Error Handling

All tools already return `{success, error, suggestion}` on failure. The frontend result area displays `error` in red with `suggestion` as subtext when `success: false`.

Long-running operations (speedtest, traceroute, full WAN speed compare) can take 30s–2min — the 10s default `httpx` timeout on backend tools must be raised for these. `run_speedtest` and `compare_wan_speed` already use longer timeouts internally; `traceroute_host` may need a timeout increase.

---

## Out of Scope

- DNS Query Log (`get_query_log`) — not selected
- Firewall Rules (`get_firewall_rules`) — not selected
- WAN Failover Policy viewer — not selected
- `get_connected_clients` — Deco firmware crash, not viable
