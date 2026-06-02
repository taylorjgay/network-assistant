# WAN Health — Design Spec

**Date:** 2026-06-02
**Status:** Approved, ready for implementation planning

## Context

The ER605 manages dual-WAN failover (WAN1: NOVOS fiber, WAN2: T-Mobile 5G), but the MCP server has no way to check whether either WAN is actually healthy — only whether a link is up. This spec adds two tools: a safe always-on health snapshot (`get_wan_health`) and a deliberate investigation tool (`compare_wan_health`) that probes both WANs independently when degradation is suspected.

## Architecture

New file `src/tools/wan_health.py` with a `WANHealthClient` class. It composes two things: a fresh `ER605Client` per call for API data and WAN switching, and `subprocess` pings (same approach as `diagnostics.py`) for active latency/loss measurement. Two methods map to two MCP tools registered in `src/server.py`.

## Tools

### `get_wan_health() -> dict`

Always safe. Pulls per-interface stats from the ER605 API for both WANs, then concurrently pings three targets (`1.1.1.1`, `8.8.8.8`, `8.8.4.4`) with 5 packets each through the active WAN. Results are averaged across all three targets for a stable reading.

**Success response:**
```python
{
    "success": True,
    "active_wan": "WAN1",
    "wan1": {
        "link": "up",
        "ip": "192.168.1.70",
        "gateway": "192.168.1.254",
        "bytes_in": 1234567890,
        "bytes_out": 987654321
    },
    "wan2": {
        "link": "up",
        "ip": "192.168.12.153",
        "gateway": "192.168.12.1",
        "bytes_in": 12345678,
        "bytes_out": 9876543
    },
    "probe": {
        "targets": ["1.1.1.1", "8.8.8.8", "8.8.4.4"],
        "avg_latency_ms": 14.2,
        "packet_loss_pct": 0.0
    },
    "degraded": False
}
```

**Degraded flag:** `packet_loss_pct > 5` OR `avg_latency_ms > 150`. Conservative thresholds — fiber (WAN1) sits at 10–20ms, 5G (WAN2) at 30–60ms under load, so 150ms is a clear signal without false positives in either mode.

Interface fields (`ip`, `gateway`, `bytes_in`, `bytes_out`) may be `null` for a WAN that is link-down or where the ER605 API omits the field.

### `compare_wan_health() -> dict`

Deliberate investigation tool. Temporarily forces WAN1 primary, waits 2 seconds for new connections to route through it, probes, then does the same for WAN2, then restores the original priority. Existing connections (VPNs, video calls) stay alive on their current paths during the switch — only new connections are affected during the ~2s windows.

Tool description notes the brief routing disruption so Claude warns the user before invoking.

**Success response:**
```python
{
    "success": True,
    "original_policy": "WAN1",
    "wan1_probe": {
        "avg_latency_ms": 14.2,
        "packet_loss_pct": 0.0,
        "degraded": False
    },
    "wan2_probe": {
        "avg_latency_ms": 42.1,
        "packet_loss_pct": 0.0,
        "degraded": False
    },
    "recommendation": "WAN1 is healthier — stay on current configuration",
    "restored": True
}
```

`restored: True` confirms original priority was reinstated. Restoration is attempted in a `finally` block — if the probes fail mid-way, restoration still runs before returning. `restored: False` means the user should manually verify WAN priority via the ER605 web UI.

**Recommendation strings:**
- `"WAN1 is healthier — stay on current configuration"`
- `"WAN2 is healthier — consider switching primary WAN"`
- `"Both WANs degraded — check upstream connections"`
- `"Both WANs healthy — WAN1 has lower latency"` (when WAN2 is also fine but WAN1 is faster)

No `dry_run` parameter — calling this tool is always intentional.

## ER605 API

Interface stats come from `interface/status2` (known-working endpoint). `active_wan` is derived from the same response — the ER605 marks whichever WAN is currently routing (which may differ from the configured priority if failover has occurred). If the field is absent in the API response, `active_wan` falls back to the configured primary from `get_wan_policy`. The `get_wan_policy` and `set_wan_priority` methods (already implemented in Phase 2) are used by `compare_wan_health` to read and restore priority.

`WANHealthClient` creates a fresh `ER605Client(**vars(cfg.er605))` per method call, consistent with the singleton-bug fix pattern used across all tools.

## Ping Implementation

Uses `subprocess.run(['ping', '-c', '5', '-i', '0.2', target])` per target (5 packets at 0.2s intervals, ~1s per target). Three targets run concurrently via `ThreadPoolExecutor`. Parses `ping` stdout for `avg` latency and packet loss percentage using the same approach as `diagnostics.py`.

## Error Handling

All failure paths return `{"success": False, "error": "...", "suggestion": "...", "attempted": "..."}`.

- **ER605 unreachable**: fail fast before attempting pings
- **`interface/status2` missing fields**: return what is available, null out missing fields, `success: True`
- **Ping subprocess fails**: `success: False` with suggestion to check connectivity
- **`compare_wan_health` mid-probe failure**: `finally` block attempts restore; `restored: False` in response if restore also fails
- **WAN switch fails**: abort comparison, attempt restore, return error

## Testing

New file `tests/test_wan_health.py`. Mock `ER605Client._api` for interface status responses and `subprocess.run` for ping stdout. ~15–18 tests:

- `get_wan_health` success path — verify interface fields and probe aggregation
- `get_wan_health` degraded flag — packet loss above threshold
- `get_wan_health` degraded flag — latency above threshold  
- `get_wan_health` WAN2 active (failover scenario)
- `get_wan_health` ER605 auth failure
- `get_wan_health` ping subprocess failure
- `get_wan_health` partial interface data (WAN2 link down, fields null)
- `compare_wan_health` success path — verify `set_wan_priority` called with WAN1 then WAN2, original restored
- `compare_wan_health` recommendation strings (WAN1 healthier, WAN2 healthier, both degraded)
- `compare_wan_health` restore on probe failure
- `compare_wan_health` `restored: False` when restore call itself fails
- `test_server.py` — `EXPECTED_TOOLS` updated to include both new tools

## What's Not In Scope

- Configurable ping targets or thresholds (hardcoded for now)
- Continuous background monitoring or alerting
- Historical latency trending (separate future feature)
- Per-WAN bandwidth utilization charts
- IPv6 WAN health
