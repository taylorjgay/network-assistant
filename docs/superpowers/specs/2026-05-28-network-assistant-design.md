# NetworkAssistant Design Spec
**Date:** 2026-05-28

## Overview

A Python MCP server that gives Claude Code tools to diagnose and (eventually) configure a home network. The user interacts entirely through natural language in Claude Code — no separate app or CLI to open.

## Network Topology

**ISP / WAN:**
- Nokia modem — NOVOS, 1 Gbps fiber, primary (WAN1)
- T-Mobile 5G modem — cellular, failover (WAN2)

**First floor — home office rack (startup order):**
1. Nokia modem
2. T-Mobile 5G modem
3. TP-Link ER605 — dual-WAN router, WAN1 primary / WAN2 failover
4. TP-Link Deco X55 #1 — wired to ER605, primary mesh node, acting as AP
5. TP-Link dummy switch (rack)
6. Pi-hole — DNS ad-blocking
7. Apple Time Capsule — backup / network storage

**First floor — desk (same office):**
- Small dummy switch fed by rack switch
- MacBook dock, occasional DirecTV receiver / Apple TV

**Basement:**
- 16-port TP-Link dummy switch fed by rack switch
- Deco X55 #2 — wired to basement switch
- AV setup: Xbox, Switch 2, Apple TV, etc.

**Second floor — daughter's room:**
- Deco X55 #3 — wireless backhaul (eventual goal: wired)

## Architecture

```
You + Claude Code
      ↕  MCP protocol (stdio)
NetworkAssistant MCP Server  (Python, runs on your Mac)
      ↓  HTTP over local network
  ┌──────────┬──────────┬──────────┬─────────────┐
  ER605     Deco ×3   Pi-hole   Network tools
                                  (ping/traceroute/speedtest)
```

The MCP server is a local subprocess started by Claude Code when you open this project. It has no internet exposure — all traffic is LAN-only. Credentials live in `config.json` on your Mac, never in version control.

## Build Phases

### Phase 1 — Diagnostics (this spec)

Read-only tools for understanding network state. No config changes.

### Phase 2 — Configuration (future spec)

Write tools for port forwarding, firewall rules, DNS overrides, WAN failover override. All write operations will have a dry-run mode that shows the diff before committing.

**Upgrade path:** If the reverse-engineered ER605 API proves too fragile, install the free Omada Software Controller on a Raspberry Pi. This unlocks a stable, documented REST API. User is open to this.

## Phase 1 — MCP Tools

### WAN & Router (ER605)

**`get_wan_status`**
Returns: active WAN interface (WAN1/WAN2), public IP, link state for both WANs, uptime, whether failover is currently active.
Source: ER605 reverse-engineered HTTP API.

**`get_router_info`**
Returns: firmware version, model, system uptime, CPU and memory usage.
Source: ER605 reverse-engineered HTTP API.

### Mesh Network (Deco)

**`get_connected_clients`**
Returns: all devices on the mesh with hostname, IP, MAC address, which Deco node they're connected to, connection type (wired/wireless), and band (2.4 GHz / 5 GHz).
Source: Deco local reverse-engineered API.
Enables: "What Deco is Taylor's iPhone on?", "What's the MAC for my MacBook Air?"

**`get_mesh_health`**
Returns: status of each Deco node (online/offline), backhaul type (wired vs wireless), signal strength for the wireless upstairs node.
Source: Deco local reverse-engineered API.

### DNS & Pi-hole

**`get_pihole_stats`**
Returns: total queries, block rate, top blocked domains, Pi-hole enabled/disabled status.
Source: Pi-hole REST API (official).

**`test_dns_resolution`**
Parameters: hostname, optional DNS server override.
Returns: resolved IPs, which DNS server answered, latency.
Useful for: checking if Pi-hole is blocking something it shouldn't, bypassing Pi-hole to test upstream DNS.
Source: Pi-hole REST API + system DNS resolver.

### Connectivity

**`ping_host`**
Parameters: host (IP or hostname), count (default 4).
Returns: min/avg/max latency, packet loss percentage.
Works for both LAN devices and internet hosts.

**`traceroute_host`**
Parameters: host.
Returns: each hop with IP and latency.
Source: system `traceroute`.

**`run_speedtest`**
Returns: download Mbps, upload Mbps, latency, test server.
Source: `speedtest-cli` Python library.

## Project Structure

```
NetworkAssistant/
├── CLAUDE.md
├── config.example.json     # Committed — shows required fields with placeholder values
├── config.json             # Gitignored — real device IPs and credentials
├── requirements.txt
├── .gitignore
└── src/
    ├── server.py           # MCP server entry point; registers all tools
    ├── config.py           # Loads and validates config.json
    └── tools/
        ├── diagnostics.py  # ping, traceroute, speedtest, DNS resolution
        ├── er605.py        # ER605 session-based HTTP client
        ├── deco.py         # Deco local API client (AES challenge-response auth)
        └── pihole.py       # Pi-hole REST client
```

## Configuration Schema

`config.json` (gitignored):
```json
{
  "er605": {
    "host": "192.168.x.x",
    "username": "admin",
    "password": "..."
  },
  "deco": {
    "host": "192.168.x.x",
    "password": "..."
  },
  "pihole": {
    "host": "192.168.x.x",
    "api_token": "..."
  }
}
```

Config is loaded once at server startup. If required fields are missing, the server logs a clear message and marks the affected tools as unavailable rather than crashing.

## Device Integration Notes

**ER605 (standalone, no Omada controller)**
Uses the reverse-engineered session-based API that the router's own web UI calls. Pattern: POST login → receive session cookie → make data requests → logout. Community projects (tplink-router Python library) have documented the relevant endpoints. Behavior may vary by firmware version — tool errors should report the firmware version to aid debugging.

**Deco X55 (local API)**
TP-Link Deco uses AES-encrypted challenge-response authentication for its local API. The `tplink_deco` Home Assistant integration has a well-tested Python implementation of this protocol. The primary Deco node (wired to ER605) is the API entry point; it reports data for all nodes in the mesh.

**Pi-hole**
Official REST API. v5 uses `/api.php` query params; v6 uses `/api/` REST endpoints. The client will detect which version is running and use the appropriate path.

**Network tools**
`ping` and `traceroute` invoked via Python subprocess. `speedtest-cli` used as a Python library. All wrapped with timeouts to prevent tool calls from hanging.

## Error Handling

Every tool returns structured output on failure — not raw exceptions. Format:
```
{
  "success": false,
  "error": "ER605 authentication failed",
  "suggestion": "Check 'er605.password' in config.json",
  "attempted": "POST http://192.168.0.1/data/login.json"
}
```

This lets Claude reason about failures and give you actionable next steps rather than printing a stack trace.

## Claude Code Registration

After implementation, add to `.claude/mcp_settings.json` in this project:
```json
{
  "mcpServers": {
    "network-assistant": {
      "command": "python",
      "args": ["src/server.py"],
      "cwd": "/Users/taylorgay/Documents/Claude/Projects/NetworkAssistant"
    }
  }
}
```

## Security Considerations

- `config.json` is gitignored and stays on your Mac only
- All device communication is LAN-only; the MCP server has no open ports
- Phase 2 write tools will require explicit confirmation before any change is applied
- The server runs only when Claude Code is active — no persistent background process with network access
- Reverse-engineered APIs mean credentials are transmitted in plaintext to local devices over your LAN (same as using the router web UI from a browser)
