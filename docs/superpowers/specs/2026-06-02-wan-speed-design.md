# Dual-WAN Speed Comparison Design

**Date:** 2026-06-02
**Status:** Approved

## Overview

Add a `compare_wan_speed` MCP tool that measures download speed, upload speed, and latency on WAN1 and WAN2 back-to-back, then produces a weighted recommendation. Supports a `quick` mode (latency only, ~15 seconds) and a full mode (complete Ookla speedtest, ~2–3 minutes).

## Structure

**New file:** `src/tools/wan_speed.py`
**Class:** `WANSpeedClient(**kwargs)` — same constructor pattern as `WANHealthClient`; creates a fresh `ER605Client` per call via `self._er605()`.

**One public method:**
```python
compare_wan_speed(quick: bool = False) -> dict
```

Registered in `server.py` as a single MCP tool.

## Modes

### Full mode (`quick=False`)

Uses `speedtest-cli` (`speedtest` library). Procedure:
1. Switch to WAN1, run `st.get_best_server()`, save the selected server
2. Run download + upload tests on WAN1
3. Switch to WAN2, call `st.get_server([saved_server])` to force the same server
4. Run download + upload tests on WAN2

Forcing the same server ensures an apples-to-apples comparison regardless of each WAN's routing preferences.

### Quick mode (`quick=True`)

Ping probe only — same implementation as `_probe()` in `wan_health.py`: 4 pings each to `1.1.1.1`, `8.8.8.8`, `8.8.4.4` concurrently, returns `avg_latency_ms` and `packet_loss_pct`. No throughput measurement. ~15 seconds total.

## WAN Switching

Identical pattern to `compare_wan_health`:

1. Call `get_wan_policy()` → save `original` (e.g. `"WAN1"` or `"auto"`)
2. `set_wan_priority("WAN1")` → sleep 2s → measure WAN1
3. `set_wan_priority("WAN2")` → sleep 2s → measure WAN2
4. `finally`: always call `set_wan_priority(original)`; set `restored = True/False`

If a WAN switch fails, abort and return the error with `restored` status. If one WAN measurement fails but the other succeeded, return partial results with the error noted — the successful measurement is not discarded.

## Recommendation Logic

### Full mode

Normalize each metric relative to the better WAN:
- `dl_score = wanN_download / max(wan1_download, wan2_download)`
- `ul_score = wanN_upload / max(wan1_upload, wan2_upload)`
- `lat_score = min(wan1_latency, wan2_latency) / wanN_latency` (lower latency → higher score)

Weighted total: `score = dl_score × 0.4 + ul_score × 0.3 + lat_score × 0.3`

If `abs(score1 - score2) / max(score1, score2) < 0.10`: `"Both WANs comparable — no strong recommendation"`.
Otherwise: `"WAN1 recommended — 7× faster download, 2.3× lower latency"` (key reasons summarised).

### Quick mode

Latency ratio only (`lat_score`). Margin check: `abs(lat1 - lat2) / max(lat1, lat2) < 0.10` → tie. Otherwise: `"WAN1 recommended — 2.3× lower latency"`.

## Output Shape

### Full mode
```json
{
  "success": true,
  "quick": false,
  "restored": true,
  "wan1": {
    "download_mbps": 850.2,
    "upload_mbps": 45.1,
    "latency_ms": 12.4,
    "server": "NYC-01"
  },
  "wan2": {
    "download_mbps": 120.5,
    "upload_mbps": 35.2,
    "latency_ms": 28.1,
    "server": "NYC-01"
  },
  "recommendation": "WAN1 recommended — 7× faster download, 2.3× lower latency"
}
```

### Quick mode
```json
{
  "success": true,
  "quick": true,
  "restored": true,
  "wan1": {"latency_ms": 12.4, "packet_loss_pct": 0.0},
  "wan2": {"latency_ms": 28.1, "packet_loss_pct": 2.5},
  "recommendation": "WAN1 recommended — 2.3× lower latency"
}
```

### Error (partial results example)
```json
{
  "success": false,
  "error": "WAN2 switch failed: ...",
  "wan1": {"download_mbps": 850.2, "upload_mbps": 45.1, "latency_ms": 12.4, "server": "NYC-01"},
  "wan2": null,
  "restored": true
}
```

## Testing

Mock `WANSpeedClient._er605()`, `speedtest.Speedtest`, and `_probe()`. Cover:
- Full mode: both WANs succeed, recommendation logic, tie margin
- Full mode: WAN switch failure (partial results)
- Full mode: speedtest exception on WAN2
- Quick mode: both WANs succeed, recommendation
- Quick mode: latency tie (margin < 10%)
- Restore always runs (monkeypatch exception mid-test)
- `restored: false` when restore call also fails

## Dependencies

- `speedtest-cli` — already in `requirements.txt`
- No new packages required
- `_probe()` from `src/tools/wan_health.py` imported directly for quick mode latency measurement
